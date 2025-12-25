"""
JARVIS Unified Orchestrator
----------------------------
Single orchestrator file for v0.5.1+.

Consolidates Phase 1-4 orchestrators into a single import path.
Legacy orchestrator_v2.py and orchestrator_v3.py are DELETED.

Usage:
    from core.orchestrator_unified import Orchestrator, Phase4Orchestrator
    from core.orchestrator_unified import Phase2Config, Phase3Config, Phase4Config
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

# Import base orchestrator (Phase 1 - always required)
from .orchestrator import Orchestrator, OrchestratorConfig, CommandResult
from .state_machine import State
from .errors import (
    ErrorHandler, JARVISError, ErrorCategory, RetryPolicy,
    create_llm_error, create_tool_error
)

# ==============================================================================
# Phase 2 Config (LLM Planning)
# ==============================================================================

@dataclass 
class Phase2Config(OrchestratorConfig):
    """Configuration for Phase 2 orchestrator (LLM planning)."""
    mode: str = "deterministic"  # deterministic | llm
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.0-flash"
    use_mock_llm: bool = False  # Use mock for testing


# ==============================================================================
# Phase 3 Config (Memory)
# ==============================================================================

@dataclass
class Phase3Config(Phase2Config):
    """Configuration for Phase 3 orchestrator (memory + preferences)."""
    # Memory settings
    max_conversation_turns: int = 20
    max_memory_tokens: int = 4000
    context_window_tokens: int = 8000
    
    # Preference settings
    preferences_path: str = "preferences.yaml"
    
    # Feature flags
    enable_memory: bool = True
    enable_preferences: bool = True


# ==============================================================================
# Phase 4 Config (Multimodal)
# ==============================================================================

@dataclass
class Phase4Config(Phase3Config):
    """Configuration for Phase 4 orchestrator (multimodal capabilities)."""
    # Multimodal settings
    enable_screenshot: bool = True
    enable_camera: bool = True
    enable_scheduling: bool = True
    camera_id: int = 0
    screenshot_dir: Optional[str] = None
    camera_dir: Optional[str] = None


# ==============================================================================
# Phase 2 Orchestrator (LLM Planning)
# ==============================================================================

class Phase2Orchestrator(Orchestrator):
    """
    Phase 2 orchestrator with LLM planning support.
    
    Maintains backwards compatibility with Phase 1 deterministic mode.
    """
    
    def __init__(self, config: Optional[Phase2Config] = None):
        self.phase2_config = config or Phase2Config()
        super().__init__(self.phase2_config)
        
        # Phase 2 components
        self._tool_registry = None
        self._tool_executor = None
        self._llm_planner = None
        self._error_handler = ErrorHandler()
        
        self._logger = logging.getLogger("jarvis.orchestrator.phase2")
    
    def initialize(self) -> None:
        """Initialize all subsystems including Phase 2 components."""
        super().initialize()
        
        self._logger.info("Initializing Phase 2 components...")
        
        from tools.registry import create_default_tools
        from tools.executor import ToolExecutor
        
        self._tool_registry = create_default_tools()
        self._logger.info(f"Tool registry loaded: {len(self._tool_registry)} tools")
        
        self._tool_executor = ToolExecutor(
            self._tool_registry,
            config_path="config/permissions.yaml"
        )
        self._logger.info("Tool executor initialized")
        
        if self.phase2_config.mode == "llm":
            self._init_llm_planner()
        
        self._logger.info(f"Phase 2 initialized (mode: {self.phase2_config.mode})")
    
    def _init_llm_planner(self) -> None:
        """Initialize the LLM planner."""
        from planner import LLMPlanner, PlannerConfig
        from planner.llm_planner import MockLLMPlanner
        
        schemas = self._tool_registry.get_schemas_for_llm()
        
        if self.phase2_config.use_mock_llm:
            self._llm_planner = MockLLMPlanner(tool_schemas=schemas)
            self._logger.info("Using mock LLM planner")
        else:
            config = PlannerConfig(
                provider=self.phase2_config.llm_provider,
                model=self.phase2_config.llm_model
            )
            self._llm_planner = LLMPlanner(config=config, tool_schemas=schemas)
            self._logger.info(f"LLM planner initialized ({config.model})")
    
    def set_mode(self, mode: str) -> None:
        """Switch between deterministic and LLM mode."""
        if mode not in ("deterministic", "llm"):
            raise ValueError(f"Invalid mode: {mode}")
        
        self.phase2_config.mode = mode
        
        if mode == "llm" and self._llm_planner is None:
            self._init_llm_planner()
        
        self._logger.info(f"Switched to {mode} mode")
    
    def _process_text(self, text: str) -> Optional[str]:
        """Process text using appropriate mode."""
        if self.phase2_config.mode == "llm":
            return self._process_with_llm(text)
        else:
            return super()._process_text(text)
    
    def _process_with_llm(self, text: str) -> Optional[str]:
        """Process text using LLM-based planning."""
        self._state_machine.transition(State.PLANNING, "LLM planning")
        
        try:
            plan = self._llm_planner.plan(text)
            
            if not plan.is_valid:
                self._logger.warning(f"Invalid plan: {plan.error}")
                error = create_llm_error(
                    plan.error or "Invalid plan",
                    is_hallucination=plan.status.name == "UNKNOWN_TOOL"
                )
                return self._handle_error(error)
            
            if not plan.requires_tools:
                self._state_machine.transition(State.RESPONDING, "Direct response")
                self._output_result(CommandResult(
                    success=True,
                    command_id="llm.response",
                    output=plan.response_text
                ))
                return plan.response_text
            
            self._state_machine.transition(State.EXECUTING, "Executing tools")
            
            results = []
            for tool_call in plan.tool_calls:
                result = self._execute_tool_call(tool_call)
                results.append(result)
                
                if not result.success:
                    break
            
            self._state_machine.transition(State.RESPONDING, "Execution complete")
            
            if all(r.success for r in results):
                output = "\n".join(str(r.output) for r in results)
                self._output_result(CommandResult(
                    success=True,
                    command_id=",".join(tc.tool_name for tc in plan.tool_calls),
                    output=output
                ))
                return output
            else:
                failed = next(r for r in results if not r.success)
                self._output_result(CommandResult(
                    success=False,
                    command_id=failed.tool_name,
                    output=None,
                    error=failed.error
                ))
                return f"Error: {failed.error}"
                
        except Exception as e:
            self._logger.error(f"LLM processing error: {e}")
            error = JARVISError.from_exception(e, ErrorCategory.LLM_FAILURE)
            return self._handle_error(error)
    
    def _execute_tool_call(self, tool_call) -> Any:
        """Execute a single tool call with error handling."""
        self._logger.info(f"Executing tool: {tool_call.tool_name}")
        
        result = self._tool_executor.execute(
            tool_call.tool_name,
            tool_call.arguments
        )
        
        if result.success:
            self._logger.info(f"Tool result: {result.output}")
        else:
            self._logger.warning(f"Tool failed: {result.error}")
        
        return result
    
    def _handle_error(self, error: JARVISError) -> str:
        """Handle an error and return user message."""
        message = self._error_handler.handle(error)
        
        if self._state_machine.state != State.IDLE:
            self._state_machine.transition(State.ERROR, error.message)
            self._state_machine.transition(State.IDLE, "Recovered from error")
        
        self._output_result(CommandResult(
            success=False,
            command_id="error",
            output=None,
            error=message
        ))
        
        return message
    
    def get_status(self) -> Dict[str, Any]:
        """Get enhanced status including Phase 2 info."""
        status = super().get_status()
        status.update({
            "mode": self.phase2_config.mode,
            "tools_loaded": len(self._tool_registry) if self._tool_registry else 0,
            "llm_ready": self._llm_planner is not None,
        })
        return status
    
    def get_available_tools(self) -> List[str]:
        """Get list of available tool names."""
        if self._tool_registry:
            return [t.name for t in self._tool_registry.list_tools()]
        return []


# ==============================================================================
# Phase 3 Orchestrator (Memory)
# ==============================================================================

class Phase3Orchestrator(Phase2Orchestrator):
    """
    Phase 3 orchestrator with memory and personalization.
    
    Features:
    - Remembers conversation context
    - Stores user preferences
    - Manages token budget
    - Provides context to LLM
    """
    
    def __init__(self, config: Optional[Phase3Config] = None):
        self.phase3_config = config or Phase3Config()
        super().__init__(self.phase3_config)
        
        self._memory = None
        self._preferences = None
        self._context_manager = None
        
        self._logger = logging.getLogger("jarvis.orchestrator.phase3")
    
    def initialize(self) -> None:
        """Initialize all subsystems including Phase 3 components."""
        super().initialize()
        
        self._logger.info("Initializing Phase 3 components...")
        
        from memory import ConversationMemory, PreferenceStore, ContextManager
        
        if self.phase3_config.enable_memory:
            self._memory = ConversationMemory(
                max_turns=self.phase3_config.max_conversation_turns,
                max_tokens=self.phase3_config.max_memory_tokens
            )
            self._logger.info(
                f"Conversation memory initialized "
                f"(max {self.phase3_config.max_conversation_turns} turns)"
            )
        
        if self.phase3_config.enable_preferences:
            self._preferences = PreferenceStore(
                store_path=self.phase3_config.preferences_path
            )
            self._logger.info("Preference store initialized")
        
        self._context_manager = ContextManager(
            memory=self._memory,
            preferences=self._preferences,
            max_tokens=self.phase3_config.context_window_tokens
        )
        self._logger.info("Context manager initialized")
        
        self._logger.info("Phase 3 initialized")
    
    def _process_with_llm(self, text: str) -> Optional[str]:
        """Process text using LLM with memory context."""
        self._state_machine.transition(State.PLANNING, "LLM planning")
        
        try:
            if self._memory is not None:
                self._memory.add_user_turn(text)
            
            context = self._build_llm_context(text)
            plan = self._llm_planner.plan(text, context=context)
            
            if not plan.is_valid:
                self._logger.warning(f"Invalid plan: {plan.error}")
                error = create_llm_error(
                    plan.error or "Invalid plan",
                    is_hallucination=plan.status.name == "UNKNOWN_TOOL"
                )
                return self._handle_error(error)
            
            if not plan.requires_tools:
                response = plan.response_text
                
                if self._memory is not None:
                    self._memory.add_assistant_turn(response)
                
                self._state_machine.transition(State.RESPONDING, "Direct response")
                self._output_result(CommandResult(
                    success=True,
                    command_id="llm.response",
                    output=response
                ))
                return response
            
            self._state_machine.transition(State.EXECUTING, "Executing tools")
            
            results = []
            for tool_call in plan.tool_calls:
                result = self._execute_tool_call(tool_call)
                results.append(result)
                
                if self._memory is not None and result.success:
                    self._memory.add_tool_turn(
                        tool_call.tool_name,
                        tool_call.arguments,
                        result.output
                    )
                
                if not result.success:
                    break
            
            self._state_machine.transition(State.RESPONDING, "Execution complete")
            
            if all(r.success for r in results):
                output = "\n".join(str(r.output) for r in results)
                
                if self._memory is not None:
                    self._memory.add_assistant_turn(f"Result: {output}")
                
                self._output_result(CommandResult(
                    success=True,
                    command_id=",".join(tc.tool_name for tc in plan.tool_calls),
                    output=output
                ))
                return output
            else:
                failed = next(r for r in results if not r.success)
                self._output_result(CommandResult(
                    success=False,
                    command_id=failed.tool_name,
                    output=None,
                    error=failed.error
                ))
                return f"Error: {failed.error}"
                
        except Exception as e:
            self._logger.error(f"LLM processing error: {e}")
            error = JARVISError.from_exception(e, ErrorCategory.LLM_FAILURE)
            return self._handle_error(error)
    
    def _build_llm_context(self, current_input: str) -> Optional[str]:
        """Build context string for LLM from memory."""
        if not self._context_manager:
            return None
        
        if self._memory and len(self._memory) > 0:
            return self._memory.get_context_string()
        
        return None
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        if self._preferences:
            return self._preferences.get(key, default)
        return default
    
    def set_preference(self, key: str, value: Any) -> None:
        """Set a user preference (explicit update only)."""
        if self._preferences:
            self._preferences.set(key, value)
            self._logger.info(f"Preference set: {key} = {value}")
    
    def list_preferences(self) -> Dict[str, Any]:
        """List all preferences."""
        if self._preferences:
            return self._preferences.list_all()
        return {}
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        stats = {
            "memory_enabled": self._memory is not None,
            "preferences_enabled": self._preferences is not None,
            "turns": 0,
            "estimated_tokens": 0,
            "max_turns": self.phase3_config.max_conversation_turns,
            "max_tokens": self.phase3_config.max_memory_tokens,
        }
        
        if self._memory:
            stats.update({
                "turns": len(self._memory),
                "estimated_tokens": self._memory.total_tokens,
            })
        
        if self._preferences:
            stats["preferences_count"] = len(self._preferences.list_all())
        
        return stats
    
    def clear_memory(self) -> int:
        """Clear conversation memory."""
        if self._memory:
            count = self._memory.clear()
            self._logger.info(f"Cleared {count} turns from memory")
            return count
        return 0
    
    def get_conversation_summary(self) -> str:
        """Get a summary of the conversation."""
        if self._memory:
            return self._memory.summarize()
        return "No conversation history."
    
    def get_status(self) -> Dict[str, Any]:
        """Get enhanced status including Phase 3 info."""
        status = super().get_status()
        status.update({
            "memory_enabled": self._memory is not None,
            "memory_turns": len(self._memory) if self._memory else 0,
            "preferences_enabled": self._preferences is not None,
        })
        return status


# ==============================================================================
# Phase 4 Orchestrator (Multimodal)
# ==============================================================================

class Phase4Orchestrator(Phase3Orchestrator):
    """
    Phase 4: Multimodal Extensions
    
    Extends Phase 3 with:
    - Screenshot capture and analysis
    - Camera input with vision
    - Event-driven scheduling
    """
    
    def __init__(self, config: Optional[Phase4Config] = None):
        self.phase4_config = config or Phase4Config()
        super().__init__(self.phase4_config)
        
        self._screen_capture = None
        self._screen_analyzer = None
        self._camera_capture = None
        self._camera_analyzer = None
        self._event_manager = None
        
        self._logger = logging.getLogger("jarvis.orchestrator.phase4")
    
    def initialize(self) -> None:
        """Initialize all subsystems including multimodal."""
        super().initialize()
        self._initialize_phase4()
    
    def _initialize_phase4(self) -> None:
        """Initialize Phase 4 multimodal components."""
        self._logger.info("Initializing Phase 4 components...")
        
        from multimodal.screenshot import ScreenCapture, ScreenAnalyzer, ScreenRegion
        from multimodal.camera import CameraCapture, CameraAnalyzer, OPENCV_AVAILABLE
        from multimodal.events import EventManager
        
        if self.phase4_config.enable_screenshot:
            self._screen_capture = ScreenCapture(
                output_dir=self.phase4_config.screenshot_dir
            )
            self._screen_analyzer = ScreenAnalyzer()
            self._logger.info("Screenshot capture initialized")
        
        if self.phase4_config.enable_camera:
            try:
                from multimodal.camera import OPENCV_AVAILABLE
                if OPENCV_AVAILABLE:
                    self._camera_capture = CameraCapture(
                        camera_id=self.phase4_config.camera_id,
                        output_dir=self.phase4_config.camera_dir
                    )
                    self._camera_analyzer = CameraAnalyzer()
                    self._logger.info("Camera support enabled")
            except ImportError:
                self._logger.warning("Camera support unavailable (opencv not installed)")
        
        if self.phase4_config.enable_scheduling:
            self._event_manager = EventManager(orchestrator=self)
            self._event_manager.start()
            self._logger.info("Event scheduler initialized")
        
        self._register_multimodal_tools()
        
        if hasattr(self, '_llm_planner') and self._llm_planner and hasattr(self, '_tool_registry'):
            schemas = self._tool_registry.get_schemas_for_llm()
            self._llm_planner.set_tool_schemas(schemas)
            self._logger.info(f"Updated planner with {len(schemas)} tools")
        
        self._logger.info("Phase 4 initialized")
    
    def _register_multimodal_tools(self) -> None:
        """Register actual executors for multimodal tools."""
        if not hasattr(self, '_tool_registry') or self._tool_registry is None:
            return
        
        from tools.registry import Tool, ToolSchema, ToolParameter, ParameterType, PermissionLevel
        from multimodal.screenshot import ScreenRegion
        
        if self._screen_capture:
            self._tool_registry.register(Tool(
                name="take_screenshot",
                description="Capture a screenshot of the screen",
                schema=ToolSchema(parameters=[
                    ToolParameter(
                        name="region",
                        type=ParameterType.STRING,
                        description="Screen region: 'full' or 'x,y,width,height'",
                        required=False,
                        default="full"
                    ),
                    ToolParameter(
                        name="analyze",
                        type=ParameterType.BOOLEAN,
                        description="Whether to analyze the screenshot with vision",
                        required=False,
                        default=False
                    )
                ]),
                permission=PermissionLevel.READ,
                executor=self._execute_screenshot,
                category="multimodal"
            ))
        
        if self._camera_capture:
            self._tool_registry.register(Tool(
                name="capture_camera",
                description="Capture a photo from the camera",
                schema=ToolSchema(parameters=[
                    ToolParameter(
                        name="analyze",
                        type=ParameterType.BOOLEAN,
                        description="Whether to analyze the image with vision",
                        required=False,
                        default=False
                    )
                ]),
                permission=PermissionLevel.READ,
                executor=self._execute_camera,
                category="multimodal"
            ))
        
        if self._event_manager:
            self._tool_registry.register(Tool(
                name="schedule_task",
                description="Schedule a task to run at a specific time or interval",
                schema=ToolSchema(parameters=[
                    ToolParameter(
                        name="name",
                        type=ParameterType.STRING,
                        description="Name of the scheduled task",
                        required=True
                    ),
                    ToolParameter(
                        name="action",
                        type=ParameterType.STRING,
                        description="Command to execute when triggered",
                        required=True
                    ),
                    ToolParameter(
                        name="hour",
                        type=ParameterType.INTEGER,
                        description="Hour to execute (0-23)",
                        required=False
                    ),
                    ToolParameter(
                        name="minute",
                        type=ParameterType.INTEGER,
                        description="Minute to execute (0-59)",
                        required=False,
                        default=0
                    ),
                    ToolParameter(
                        name="interval_seconds",
                        type=ParameterType.INTEGER,
                        description="Interval in seconds (for repeating tasks)",
                        required=False
                    )
                ]),
                permission=PermissionLevel.EXECUTE,
                executor=self._execute_schedule,
                category="automation"
            ))
            
            self._tool_registry.register(Tool(
                name="list_scheduled_tasks",
                description="List all scheduled tasks",
                schema=ToolSchema(parameters=[]),
                permission=PermissionLevel.READ,
                executor=self._execute_list_tasks,
                category="automation"
            ))
    
    def _execute_screenshot(self, args: Dict[str, Any]) -> str:
        """Execute screenshot capture."""
        if not self._screen_capture:
            return "Screenshot capture not available"
        
        from multimodal.screenshot import ScreenRegion
        
        region_str = args.get("region", "full")
        analyze = args.get("analyze", False)
        
        region = None
        if region_str != "full":
            try:
                parts = [int(x) for x in region_str.split(",")]
                if len(parts) == 4:
                    region = ScreenRegion(x=parts[0], y=parts[1], width=parts[2], height=parts[3])
            except ValueError:
                pass
        
        screenshot = self._screen_capture.capture(region=region)
        
        if not screenshot:
            return "Failed to capture screenshot"
        
        result = f"Screenshot captured: {screenshot.path}"
        
        if analyze and self._screen_analyzer:
            analysis = self._screen_analyzer.analyze(screenshot)
            if analysis:
                result += f"\n\nAnalysis:\n{analysis}"
        
        return result
    
    def _execute_camera(self, args: Dict[str, Any]) -> str:
        """Execute camera capture."""
        if not self._camera_capture:
            return "Camera capture not available"
        
        analyze = args.get("analyze", False)
        
        frame = self._camera_capture.capture()
        
        if not frame:
            return "Failed to capture camera frame"
        
        result = f"Camera frame captured: {frame.path} ({frame.width}x{frame.height})"
        
        if analyze and self._camera_analyzer:
            analysis = self._camera_analyzer.analyze(frame)
            if analysis:
                result += f"\n\nAnalysis:\n{analysis}"
        
        return result
    
    def _execute_schedule(self, args: Dict[str, Any]) -> str:
        """Execute task scheduling."""
        if not self._event_manager:
            return "Event scheduling not available"
        
        name = args.get("name", "Unnamed task")
        action = args.get("action", "")
        hour = args.get("hour")
        minute = args.get("minute", 0)
        interval = args.get("interval_seconds")
        
        if interval:
            task = self._event_manager.schedule_interval(
                name=name,
                action=action,
                interval_seconds=interval
            )
            return f"Scheduled repeating task '{name}' every {interval} seconds (ID: {task.id})"
        elif hour is not None:
            task = self._event_manager.schedule_at(
                name=name,
                action=action,
                hour=hour,
                minute=minute
            )
            return f"Scheduled task '{name}' for {hour:02d}:{minute:02d} (ID: {task.id})"
        else:
            return "Please specify either 'hour' for daily schedule or 'interval_seconds' for repeating"
    
    def _execute_list_tasks(self, args: Dict[str, Any]) -> str:
        """List scheduled tasks."""
        if not self._event_manager:
            return "Event scheduling not available"
        
        tasks = self._event_manager.list_tasks()
        
        if not tasks:
            return "No scheduled tasks"
        
        lines = ["Scheduled tasks:"]
        for task in tasks:
            next_run = task.next_run.strftime("%H:%M:%S") if task.next_run else "N/A"
            lines.append(f"  - {task.name} ({task.id}): {task.state.name}, next: {next_run}")
        
        return "\n".join(lines)
    
    def process_text_directly(self, text: str) -> Optional[str]:
        """Process text command directly (for scheduled tasks)."""
        return self._process_with_llm(text)
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status including multimodal."""
        status = super().get_status()
        
        status.update({
            "screenshot_enabled": self._screen_capture is not None,
            "camera_enabled": self._camera_capture is not None,
            "scheduling_enabled": self._event_manager is not None,
            "scheduled_tasks": len(self._event_manager.list_tasks()) if self._event_manager else 0,
        })
        
        return status
    
    def shutdown(self) -> None:
        """Shutdown all subsystems."""
        if self._event_manager:
            self._event_manager.stop()
        
        if self._screen_capture:
            self._screen_capture.cleanup_old()
        if self._camera_capture:
            self._camera_capture.cleanup_old()
        
        super().shutdown()


# ==============================================================================
# Startup Enforcement
# ==============================================================================

def _enforce_no_legacy_orchestrators() -> None:
    """
    v0.5.1 Enforcement: Legacy orchestrator files must not exist.
    
    Hard fail if orchestrator_v2.py or orchestrator_v3.py exist.
    """
    import os
    
    core_dir = Path(__file__).parent
    
    legacy_files = [
        core_dir / "orchestrator_v2.py",
        core_dir / "orchestrator_v3.py",
    ]
    
    for legacy in legacy_files:
        if legacy.exists():
            raise RuntimeError(
                f"FATAL: Legacy orchestrator file found: {legacy}\n"
                f"v0.5.1 requires single unified orchestrator.\n"
                f"Delete legacy files: orchestrator_v2.py, orchestrator_v3.py"
            )


# Run enforcement on import
_enforce_no_legacy_orchestrators()
