"""
Audio Buffer Module
-------------------
Manages audio data storage with timestamping.
Stateless module - no imports from other JARVIS modules.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import numpy as np


@dataclass
class AudioSegment:
    """Represents a timestamped audio segment."""
    
    data: np.ndarray
    sample_rate: int
    timestamp_start: datetime
    timestamp_end: datetime
    
    @property
    def duration_seconds(self) -> float:
        """Calculate duration in seconds."""
        return len(self.data) / self.sample_rate
    
    @property
    def is_valid(self) -> bool:
        """Check if segment contains valid audio data."""
        return len(self.data) > 0 and self.sample_rate > 0
    
    def to_pcm_bytes(self) -> bytes:
        """Convert to raw PCM bytes."""
        return self.data.tobytes()
    
    def __repr__(self) -> str:
        return (
            f"AudioSegment(duration={self.duration_seconds:.2f}s, "
            f"sample_rate={self.sample_rate}, "
            f"start={self.timestamp_start.isoformat()})"
        )


@dataclass
class AudioBuffer:
    """
    Circular buffer for audio frames.
    Provides timestamped segment storage and retrieval.
    """
    
    sample_rate: int = 16000
    max_duration_seconds: float = 30.0
    _frames: list = field(default_factory=list)
    _timestamps: list = field(default_factory=list)
    _recording_start: Optional[datetime] = None
    
    def __post_init__(self):
        self._max_samples = int(self.sample_rate * self.max_duration_seconds)
    
    def start_recording(self) -> None:
        """Mark the start of a new recording session."""
        self._recording_start = datetime.now()
        self._frames = []
        self._timestamps = []
    
    def add_frame(self, frame: np.ndarray) -> None:
        """Add an audio frame to the buffer."""
        if self._recording_start is None:
            raise RuntimeError("Recording not started. Call start_recording() first.")
        
        self._frames.append(frame.copy())
        self._timestamps.append(datetime.now())
        
        # Enforce max duration by removing oldest frames
        self._enforce_max_duration()
    
    def _enforce_max_duration(self) -> None:
        """Remove oldest frames if buffer exceeds max duration."""
        total_samples = sum(len(f) for f in self._frames)
        
        while total_samples > self._max_samples and len(self._frames) > 1:
            removed = self._frames.pop(0)
            self._timestamps.pop(0)
            total_samples -= len(removed)
    
    def stop_recording(self) -> AudioSegment:
        """
        Stop recording and return the complete audio segment.
        Clears the buffer after returning.
        """
        if self._recording_start is None:
            raise RuntimeError("No active recording to stop.")
        
        if not self._frames:
            # Return empty segment
            segment = AudioSegment(
                data=np.array([], dtype=np.float32),
                sample_rate=self.sample_rate,
                timestamp_start=self._recording_start,
                timestamp_end=datetime.now()
            )
        else:
            # Concatenate all frames
            combined_data = np.concatenate(self._frames)
            segment = AudioSegment(
                data=combined_data,
                sample_rate=self.sample_rate,
                timestamp_start=self._recording_start,
                timestamp_end=self._timestamps[-1]
            )
        
        # Clear buffer
        self._frames = []
        self._timestamps = []
        self._recording_start = None
        
        return segment
    
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording_start is not None
    
    def get_current_duration(self) -> float:
        """Get current recording duration in seconds."""
        if not self._frames:
            return 0.0
        return sum(len(f) for f in self._frames) / self.sample_rate
    
    def clear(self) -> None:
        """Clear all buffered data."""
        self._frames = []
        self._timestamps = []
        self._recording_start = None
