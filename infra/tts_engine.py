"""
TTS Engine
----------
Text-to-speech integration for voice output.
Supports multiple backends: edge-tts, piper (optional).

No autonomous speech - all TTS is triggered by commands.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import asyncio
import io
import logging
import os
import tempfile

try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False


class TTSBackend(Enum):
    """Available TTS backends."""
    EDGE = "edge"      # Microsoft Edge TTS (free, online)
    PIPER = "piper"    # Piper TTS (offline, optional)
    SYSTEM = "system"  # macOS say command


@dataclass
class Voice:
    """Voice configuration."""
    name: str
    language: str = "en"
    gender: str = "neutral"
    backend: TTSBackend = TTSBackend.EDGE
    
    # Edge TTS voices
    EDGE_VOICES = {
        "jenny": "en-US-JennyNeural",
        "guy": "en-US-GuyNeural",
        "aria": "en-US-AriaNeural",
        "davis": "en-US-DavisNeural",
        "jane": "en-US-JaneNeural",
        "jason": "en-US-JasonNeural",
        "sara": "en-US-SaraNeural",
        "tony": "en-US-TonyNeural",
        "nancy": "en-US-NancyNeural",
    }
    
    def get_voice_id(self) -> str:
        """Get the backend-specific voice ID."""
        if self.backend == TTSBackend.EDGE:
            return self.EDGE_VOICES.get(self.name.lower(), "en-US-JennyNeural")
        return self.name


@dataclass
class TTSConfig:
    """TTS engine configuration."""
    backend: TTSBackend = TTSBackend.EDGE
    voice: str = "jenny"
    rate: str = "+0%"  # Speed adjustment
    volume: str = "+0%"  # Volume adjustment
    pitch: str = "+0Hz"  # Pitch adjustment
    output_format: str = "audio-24khz-48kbitrate-mono-mp3"
    cache_dir: Optional[str] = None
    

class TTSEngine:
    """
    Text-to-speech engine.
    
    Supports:
    - Edge TTS (online, high quality, free)
    - Piper TTS (offline, optional)
    - System TTS (macOS say command)
    """
    
    def __init__(self, config: Optional[TTSConfig] = None):
        self.config = config or TTSConfig()
        self._logger = logging.getLogger("jarvis.infra.tts")
        self._cache_dir = Path(config.cache_dir) if config and config.cache_dir else Path(tempfile.gettempdir()) / "jarvis_tts"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Verify backend availability
        self._verify_backend()
    
    def _verify_backend(self) -> None:
        """Verify the TTS backend is available."""
        if self.config.backend == TTSBackend.EDGE:
            try:
                import edge_tts
                self._logger.info("Edge TTS backend available")
            except ImportError:
                self._logger.warning("edge-tts not installed, falling back to system")
                self.config.backend = TTSBackend.SYSTEM
        
        elif self.config.backend == TTSBackend.PIPER:
            try:
                import piper
                self._logger.info("Piper TTS backend available")
            except ImportError:
                self._logger.warning("piper-tts not installed, falling back to edge")
                self.config.backend = TTSBackend.EDGE
    
    async def speak(self, text: str, voice: Optional[Voice] = None) -> bool:
        """
        Speak the given text.
        
        Returns True if speech was successful.
        """
        if not text.strip():
            return False
        
        self._logger.info(f"Speaking: {text[:50]}...")
        
        try:
            if self.config.backend == TTSBackend.EDGE:
                return await self._speak_edge(text, voice)
            elif self.config.backend == TTSBackend.PIPER:
                return await self._speak_piper(text, voice)
            elif self.config.backend == TTSBackend.SYSTEM:
                return await self._speak_system(text, voice)
            else:
                self._logger.error(f"Unknown backend: {self.config.backend}")
                return False
                
        except Exception as e:
            self._logger.error(f"TTS error: {e}")
            return False
    
    async def _speak_edge(self, text: str, voice: Optional[Voice] = None) -> bool:
        """Speak using Edge TTS."""
        import edge_tts
        
        voice_id = voice.get_voice_id() if voice else Voice(self.config.voice).get_voice_id()
        
        # Create communicate object
        communicate = edge_tts.Communicate(
            text,
            voice_id,
            rate=self.config.rate,
            volume=self.config.volume,
            pitch=self.config.pitch
        )
        
        # Generate audio to temp file
        temp_file = self._cache_dir / f"tts_{hash(text) & 0xffffffff}.mp3"
        
        await communicate.save(str(temp_file))
        
        # Play audio
        await self._play_audio_file(temp_file)
        
        return True
    
    async def _speak_piper(self, text: str, voice: Optional[Voice] = None) -> bool:
        """Speak using Piper TTS."""
        try:
            from piper import PiperVoice
            
            # This requires a downloaded voice model
            # For now, fall back to edge
            self._logger.warning("Piper requires voice models, falling back to Edge")
            return await self._speak_edge(text, voice)
            
        except Exception as e:
            self._logger.error(f"Piper TTS error: {e}")
            return await self._speak_edge(text, voice)
    
    async def _speak_system(self, text: str, voice: Optional[Voice] = None) -> bool:
        """Speak using system TTS (macOS say command)."""
        import platform
        import subprocess
        
        if platform.system() != "Darwin":
            self._logger.warning("System TTS only available on macOS")
            return False
        
        # Escape text for shell
        safe_text = text.replace('"', '\\"')
        
        process = await asyncio.create_subprocess_exec(
            "say", safe_text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        await process.wait()
        return process.returncode == 0
    
    async def _play_audio_file(self, path: Path) -> None:
        """Play an audio file."""
        if not AUDIO_AVAILABLE:
            self._logger.warning("sounddevice not available for playback")
            return
        
        try:
            # Use ffmpeg or similar to decode MP3 to raw audio
            import subprocess
            
            # Convert MP3 to WAV using ffmpeg
            wav_path = path.with_suffix('.wav')
            
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(path), "-ar", "24000", "-ac", "1", str(wav_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await process.wait()
            
            if wav_path.exists():
                # Read and play WAV
                import wave
                
                with wave.open(str(wav_path), 'rb') as wf:
                    data = wf.readframes(wf.getnframes())
                    audio = np.frombuffer(data, dtype=np.int16)
                    
                    # Play audio
                    sd.play(audio, samplerate=wf.getframerate())
                    sd.wait()
                
                # Cleanup
                wav_path.unlink(missing_ok=True)
            
        except Exception as e:
            self._logger.error(f"Audio playback error: {e}")
    
    def speak_sync(self, text: str, voice: Optional[Voice] = None) -> bool:
        """Synchronous speak wrapper."""
        return asyncio.run(self.speak(text, voice))
    
    def get_available_voices(self) -> List[str]:
        """Get list of available voice names."""
        if self.config.backend == TTSBackend.EDGE:
            return list(Voice.EDGE_VOICES.keys())
        return []
    
    def set_voice(self, voice_name: str) -> None:
        """Set the current voice."""
        self.config.voice = voice_name
        self._logger.info(f"Voice set to: {voice_name}")
    
    def set_rate(self, rate: str) -> None:
        """Set speech rate (e.g., '+20%', '-10%')."""
        self.config.rate = rate
    
    def set_volume(self, volume: str) -> None:
        """Set volume (e.g., '+20%', '-10%')."""
        self.config.volume = volume


async def test_tts() -> None:
    """Test TTS engine."""
    print("Testing TTS Engine...")
    
    config = TTSConfig(backend=TTSBackend.EDGE)
    engine = TTSEngine(config)
    
    print(f"Backend: {config.backend.value}")
    print(f"Available voices: {engine.get_available_voices()}")
    
    # Test speech
    print("\nTesting speech...")
    success = await engine.speak("Hello! I am JARVIS, your voice assistant.")
    print(f"Speech result: {'Success' if success else 'Failed'}")
    
    print("\nAll tests complete!")


if __name__ == "__main__":
    asyncio.run(test_tts())
