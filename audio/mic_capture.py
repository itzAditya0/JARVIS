"""
Microphone Capture Module
-------------------------
Push-to-talk audio capture using sounddevice.
Stateless module - no imports from other JARVIS modules.

Exit Criterion: Audio capture is testable without STT.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional
import threading
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

from .audio_buffer import AudioBuffer, AudioSegment


class CaptureEvent(Enum):
    """Events emitted by the microphone capture system."""
    STARTED = auto()
    STOPPED = auto()
    FRAME_CAPTURED = auto()
    ERROR = auto()


@dataclass
class CaptureConfig:
    """Configuration for microphone capture."""
    sample_rate: int = 16000
    channels: int = 1
    dtype: str = "float32"
    block_size: int = 1024  # Samples per callback


class MicrophoneCapture:
    """
    Push-to-talk microphone capture.
    
    Usage:
        capture = MicrophoneCapture(config)
        capture.start()  # Begin recording
        # ... user speaks ...
        segment = capture.stop()  # Get AudioSegment
    """
    
    def __init__(
        self,
        config: Optional[CaptureConfig] = None,
        on_event: Optional[Callable[[CaptureEvent, Optional[dict]], None]] = None
    ):
        if sd is None:
            raise ImportError("sounddevice is required. Install with: pip install sounddevice")
        
        self.config = config or CaptureConfig()
        self.on_event = on_event
        
        self._buffer = AudioBuffer(
            sample_rate=self.config.sample_rate,
            max_duration_seconds=30.0
        )
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
    
    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status
    ) -> None:
        """Callback for audio frames from sounddevice."""
        if status:
            self._emit_event(CaptureEvent.ERROR, {"status": str(status)})
        
        # Copy data to avoid buffer reuse issues
        audio_data = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        
        with self._lock:
            if self._buffer.is_recording():
                self._buffer.add_frame(audio_data)
                self._emit_event(CaptureEvent.FRAME_CAPTURED, {
                    "samples": len(audio_data),
                    "duration": self._buffer.get_current_duration()
                })
    
    def _emit_event(self, event: CaptureEvent, data: Optional[dict] = None) -> None:
        """Emit an event to the callback if registered."""
        if self.on_event:
            try:
                self.on_event(event, data)
            except Exception:
                pass  # Don't let callback errors break capture
    
    def start(self) -> None:
        """Start recording audio."""
        with self._lock:
            if self._stream is not None:
                raise RuntimeError("Capture already in progress")
            
            self._buffer.start_recording()
            
            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                blocksize=self.config.block_size,
                callback=self._audio_callback
            )
            self._stream.start()
            self._emit_event(CaptureEvent.STARTED)
    
    def stop(self) -> AudioSegment:
        """Stop recording and return the captured audio segment."""
        with self._lock:
            if self._stream is None:
                raise RuntimeError("No capture in progress")
            
            self._stream.stop()
            self._stream.close()
            self._stream = None
            
            segment = self._buffer.stop_recording()
            self._emit_event(CaptureEvent.STOPPED, {
                "duration": segment.duration_seconds
            })
            
            return segment
    
    def is_capturing(self) -> bool:
        """Check if currently capturing audio."""
        with self._lock:
            return self._stream is not None
    
    def get_current_duration(self) -> float:
        """Get current recording duration in seconds."""
        with self._lock:
            return self._buffer.get_current_duration()


def test_capture(duration_seconds: float = 3.0) -> AudioSegment:
    """
    Test microphone capture standalone.
    Records for specified duration and returns the segment.
    """
    import time
    
    print(f"Testing microphone capture for {duration_seconds} seconds...")
    print("Speak into your microphone.")
    
    events = []
    
    def on_event(event: CaptureEvent, data: Optional[dict]) -> None:
        events.append((event, data))
    
    capture = MicrophoneCapture(on_event=on_event)
    capture.start()
    
    time.sleep(duration_seconds)
    
    segment = capture.stop()
    
    print(f"\nCapture complete!")
    print(f"  Duration: {segment.duration_seconds:.2f}s")
    print(f"  Samples: {len(segment.data)}")
    print(f"  Sample rate: {segment.sample_rate} Hz")
    print(f"  Events captured: {len(events)}")
    
    return segment


if __name__ == "__main__":
    # Run standalone test
    test_capture()
