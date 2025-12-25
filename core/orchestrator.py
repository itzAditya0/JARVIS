"""
Orchestrator
------------
Central coordinator for all JARVIS subsystems.
All interactions flow through the orchestrator.

Non-negotiable rule: No direct imports across layers.
All interactions go through this module.

Exit Criterion: End-to-end voice command works without LLMs.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import logging
import yaml

from .state_machine import StateMachine, State


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""
    config_path: str = "config.yaml"
    max_retries: int = 2
    timeout_seconds: float = 30.0
    confidence_threshold: float = 0.6


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    command_id: str
    output: Any
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    
    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"CommandResult({status} {self.command_id}, output={self.output})"


class Orchestrator:
    """
    Central orchestrator for JARVIS.
    
    Responsibilities:
    - State management
    - Module coordination
    - Error routing
    - Logging orchestration
    
    This is the ONLY entry point for system operations.
    """
    
    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()
        self._state_machine = StateMachine()
        self._logger = logging.getLogger("jarvis.orchestrator")
        
        # Lazy-loaded modules
        self._mic_capture = None
        self._stt_engine = None
        self._command_registry = None
        self._permission_checker = None
        self._executor = None
        
        # Event callbacks
        self._on_transcription: Optional[Callable[[str, float], None]] = None
        self._on_command: Optional[Callable[[str, Dict], None]] = None
        self._on_result: Optional[Callable[[CommandResult], None]] = None
        
        # Load configuration
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        config_path = Path(self.config.config_path)
        
        if config_path.exists():
            with open(config_path, 'r') as f:
                self._yaml_config = yaml.safe_load(f)
        else:
            self._yaml_config = {}
            self._logger.warning(f"Config file not found: {config_path}")
    
    @property
    def state(self) -> State:
        """Get current system state."""
        return self._state_machine.state
    
    def initialize(self) -> None:
        """
        Initialize all subsystems.
        Call this before starting the main loop.
        """
        self._logger.info("Initializing JARVIS subsystems...")
        
        # Import modules here to avoid circular imports
        from audio import MicrophoneCapture, CaptureConfig
        from stt import WhisperEngine, STTConfig
        from commands import CommandRegistry
        from security import PermissionChecker
        
        # Initialize audio capture
        audio_config = self._yaml_config.get('audio', {})
        self._mic_capture = MicrophoneCapture(
            config=CaptureConfig(
                sample_rate=audio_config.get('sample_rate', 16000),
                channels=audio_config.get('channels', 1),
                dtype=audio_config.get('dtype', 'float32')
            )
        )
        self._logger.info("Audio capture initialized")
        
        # Initialize STT engine
        stt_config = self._yaml_config.get('stt', {})
        self._stt_engine = WhisperEngine(
            config=STTConfig(
                model=stt_config.get('model', 'medium'),
                language=stt_config.get('language', 'en'),
                beam_size=stt_config.get('beam_size', 5),
                confidence_threshold=stt_config.get('confidence_threshold', 0.6),
                device=stt_config.get('device', 'auto')
            )
        )
        self._logger.info("STT engine initialized")
        
        # Initialize command registry
        commands_config = self._yaml_config.get('commands', {})
        registry_path = commands_config.get('registry_path', 'commands/command_map.yaml')
        self._command_registry = CommandRegistry(registry_path)
        self._logger.info(f"Command registry loaded: {len(self._command_registry)} commands")
        
        # Initialize permission checker
        security_config = self._yaml_config.get('security', {})
        self._permission_checker = PermissionChecker(
            default_policy=security_config.get('default_policy', 'deny')
        )
        self._logger.info("Permission checker initialized")
        
        self._logger.info("All subsystems initialized successfully")
    
    def start_listening(self) -> None:
        """Start capturing audio (push-to-talk activated)."""
        if self._state_machine.state != State.IDLE:
            self._logger.warning(f"Cannot start listening in state: {self._state_machine.state}")
            return
        
        self._state_machine.transition(State.LISTENING, "Push-to-talk activated")
        
        try:
            self._mic_capture.start()
            self._logger.info("Microphone capture started")
        except Exception as e:
            self._logger.error(f"Failed to start capture: {e}")
            self._state_machine.transition(State.ERROR, f"Capture error: {e}")
    
    def stop_listening(self) -> Optional[str]:
        """
        Stop capturing audio and process the result.
        Returns the recognized text if successful.
        """
        if self._state_machine.state != State.LISTENING:
            self._logger.warning(f"Cannot stop listening in state: {self._state_machine.state}")
            return None
        
        try:
            # Get audio segment
            audio_segment = self._mic_capture.stop()
            self._logger.info(f"Captured audio: {audio_segment.duration_seconds:.2f}s")
            
            if audio_segment.duration_seconds < 0.5:
                self._logger.warning("Audio too short, ignoring")
                self._state_machine.transition(State.IDLE, "Audio too short")
                return None
            
            # Transition to transcribing
            self._state_machine.transition(State.TRANSCRIBING, "Audio captured")
            
            # Ensure STT model is loaded
            if not self._stt_engine.is_loaded:
                self._logger.info("Loading STT model...")
                self._stt_engine.load()
            
            # Transcribe
            result = self._stt_engine.transcribe(
                audio_segment.data,
                audio_segment.sample_rate
            )
            
            self._logger.info(
                f"Transcription: '{result.text}' "
                f"(confidence: {result.confidence:.2%})"
            )
            
            # Check confidence threshold
            threshold = self._yaml_config.get('stt', {}).get('confidence_threshold', 0.6)
            
            if not result.meets_threshold(threshold):
                self._logger.warning(
                    f"Confidence {result.confidence:.2%} below threshold {threshold:.2%}"
                )
                self._state_machine.transition(State.IDLE, "Low confidence transcription")
                return None
            
            if result.is_empty:
                self._logger.info("Empty transcription")
                self._state_machine.transition(State.IDLE, "No speech detected")
                return None
            
            # Notify callback
            if self._on_transcription:
                self._on_transcription(result.text, result.confidence)
            
            # Process the transcription
            return self._process_text(result.text)
            
        except Exception as e:
            self._logger.error(f"Processing error: {e}")
            self._state_machine.transition(State.ERROR, f"Processing error: {e}")
            self._state_machine.transition(State.IDLE, "Recovered from error")
            return None
    
    def _process_text(self, text: str) -> Optional[str]:
        """Process transcribed text through command matching and execution."""
        # Transition to planning (command matching in Phase 1)
        self._state_machine.transition(State.PLANNING, "Matching command")
        
        # Match command
        intent = self._command_registry.match(text)
        
        if not intent.is_match:
            self._logger.info(f"No command matched for: '{text}'")
            self._state_machine.transition(State.RESPONDING, "No command matched")
            
            # Output result
            output = f"I didn't understand: '{text}'"
            self._output_result(CommandResult(
                success=False,
                command_id="",
                output=output,
                error="No command matched"
            ))
            return output
        
        self._logger.info(f"Command matched: {intent.command_id}")
        
        # Notify callback
        if self._on_command:
            self._on_command(intent.command_id, intent.args)
        
        # Check permission
        if not self._permission_checker.check(intent.command_id, intent.permission):
            self._logger.warning(f"Permission denied for: {intent.command_id}")
            self._state_machine.transition(State.RESPONDING, "Permission denied")
            
            output = f"Permission denied for: {intent.command_name}"
            self._output_result(CommandResult(
                success=False,
                command_id=intent.command_id,
                output=output,
                error="Permission denied"
            ))
            return output
        
        # Execute command
        self._state_machine.transition(State.EXECUTING, f"Executing {intent.command_id}")
        
        start_time = datetime.now()
        
        try:
            # Get executor and run command
            if self._executor is None:
                from security import CommandExecutor
                self._executor = CommandExecutor()
            
            result = self._executor.execute(intent)
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            self._state_machine.transition(State.RESPONDING, "Execution complete")
            
            cmd_result = CommandResult(
                success=True,
                command_id=intent.command_id,
                output=result,
                execution_time_ms=execution_time
            )
            
            self._output_result(cmd_result)
            return str(result)
            
        except Exception as e:
            self._logger.error(f"Execution error: {e}")
            self._state_machine.transition(State.ERROR, f"Execution error: {e}")
            
            cmd_result = CommandResult(
                success=False,
                command_id=intent.command_id,
                output=None,
                error=str(e)
            )
            
            self._state_machine.transition(State.IDLE, "Recovered from error")
            self._output_result(cmd_result)
            return f"Error: {e}"
    
    def _output_result(self, result: CommandResult) -> None:
        """Output command result to CLI."""
        if result.success:
            self._logger.info(f"Command result: {result.output}")
        else:
            self._logger.error(f"Command failed: {result.error}")
        
        # Notify callback
        if self._on_result:
            self._on_result(result)
        
        # Transition back to idle
        if self._state_machine.state != State.IDLE:
            self._state_machine.transition(State.IDLE, "Result delivered")
    
    def process_text_directly(self, text: str) -> Optional[str]:
        """
        Process text input directly (bypass audio capture).
        Useful for testing and CLI input.
        """
        if self._state_machine.state != State.IDLE:
            self._logger.warning(f"Cannot process in state: {self._state_machine.state}")
            return None
        
        self._logger.info(f"Processing text: '{text}'")
        return self._process_text(text)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current system status."""
        return {
            "state": self._state_machine.state.name,
            "is_busy": self._state_machine.is_busy(),
            "stt_loaded": self._stt_engine.is_loaded if self._stt_engine else False,
            "commands_loaded": len(self._command_registry) if self._command_registry else 0,
        }
    
    def shutdown(self) -> None:
        """Shutdown all subsystems."""
        self._logger.info("Shutting down JARVIS...")
        
        if self._stt_engine and self._stt_engine.is_loaded:
            self._stt_engine.unload()
        
        self._logger.info("Shutdown complete")
    
    # Event registration
    def on_transcription(self, callback: Callable[[str, float], None]) -> None:
        """Register callback for transcription events."""
        self._on_transcription = callback
    
    def on_command(self, callback: Callable[[str, Dict], None]) -> None:
        """Register callback for command match events."""
        self._on_command = callback
    
    def on_result(self, callback: Callable[[CommandResult], None]) -> None:
        """Register callback for command result events."""
        self._on_result = callback
