"""
Whisper STT Engine
------------------
Local speech-to-text using Faster-Whisper.
Stateless module - can be swapped without touching other modules.

Exit Criterion: STT can be swapped without touching other modules.
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None


@dataclass
class STTConfig:
    """Configuration for the STT engine."""
    model: str = "medium"  # tiny, base, small, medium, large-v3
    language: str = "en"   # Locked language
    beam_size: int = 5
    confidence_threshold: float = 0.6
    device: str = "auto"   # auto, cpu, cuda
    compute_type: str = "auto"  # auto, int8, float16, float32


@dataclass
class TranscriptionResult:
    """Result of a transcription with confidence score."""
    
    text: str
    confidence: float
    language: str
    duration_seconds: float
    
    @property
    def is_confident(self) -> bool:
        """Check if transcription meets confidence threshold (0.6 default)."""
        return self.confidence >= 0.6
    
    def meets_threshold(self, threshold: float) -> bool:
        """Check if transcription meets a custom confidence threshold."""
        return self.confidence >= threshold
    
    @property
    def is_empty(self) -> bool:
        """Check if transcription is empty or whitespace."""
        return not self.text or not self.text.strip()
    
    def __repr__(self) -> str:
        return (
            f"TranscriptionResult(text='{self.text[:50]}{'...' if len(self.text) > 50 else ''}', "
            f"confidence={self.confidence:.2f}, language={self.language})"
        )


class WhisperEngine:
    """
    Faster-Whisper based speech-to-text engine.
    
    Key constraints:
    - Language is locked (no auto-detection)
    - Confidence score is always exposed
    - Stateless - no context carried between calls
    """
    
    def __init__(self, config: Optional[STTConfig] = None):
        if WhisperModel is None:
            raise ImportError(
                "faster-whisper is required. Install with: pip install faster-whisper"
            )
        
        self.config = config or STTConfig()
        self._model: Optional[WhisperModel] = None
        self._loaded = False
    
    def load(self) -> None:
        """Load the Whisper model into memory."""
        if self._loaded:
            return
        
        # Determine device and compute type
        device = self.config.device
        compute_type = self.config.compute_type
        
        if device == "auto":
            device = "cuda"  # Will fall back to CPU if CUDA unavailable
            compute_type = "float16" if compute_type == "auto" else compute_type
        elif device == "cpu":
            compute_type = "int8" if compute_type == "auto" else compute_type
        
        try:
            self._model = WhisperModel(
                self.config.model,
                device=device,
                compute_type=compute_type
            )
        except Exception:
            # Fallback to CPU if GPU fails
            self._model = WhisperModel(
                self.config.model,
                device="cpu",
                compute_type="int8"
            )
        
        self._loaded = True
    
    def transcribe(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000
    ) -> TranscriptionResult:
        """
        Transcribe audio data to text.
        
        Args:
            audio_data: NumPy array of audio samples (float32, mono)
            sample_rate: Sample rate of audio data (should be 16kHz)
        
        Returns:
            TranscriptionResult with text and confidence score
        """
        if not self._loaded:
            self.load()
        
        if len(audio_data) == 0:
            return TranscriptionResult(
                text="",
                confidence=0.0,
                language=self.config.language,
                duration_seconds=0.0
            )
        
        # Resample if necessary (Whisper expects 16kHz)
        if sample_rate != 16000:
            audio_data = self._resample(audio_data, sample_rate, 16000)
        
        # Ensure float32
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)
        
        # Normalize audio
        max_val = np.abs(audio_data).max()
        if max_val > 0:
            audio_data = audio_data / max_val
        
        # Transcribe with locked language
        segments, info = self._model.transcribe(
            audio_data,
            language=self.config.language,
            beam_size=self.config.beam_size,
            vad_filter=True,  # Voice activity detection
            vad_parameters=dict(
                min_silence_duration_ms=500
            )
        )
        
        # Collect segments and calculate average confidence
        texts = []
        confidences = []
        
        for segment in segments:
            texts.append(segment.text)
            # Use average log probability as confidence proxy
            # Convert from log probability to 0-1 range
            confidence = np.exp(segment.avg_logprob)
            confidences.append(confidence)
        
        full_text = "".join(texts).strip()
        avg_confidence = np.mean(confidences) if confidences else 0.0
        
        # Clamp confidence to 0-1 range
        avg_confidence = max(0.0, min(1.0, float(avg_confidence)))
        
        return TranscriptionResult(
            text=full_text,
            confidence=avg_confidence,
            language=self.config.language,
            duration_seconds=len(audio_data) / 16000
        )
    
    def _resample(
        self,
        audio: np.ndarray,
        orig_sr: int,
        target_sr: int
    ) -> np.ndarray:
        """Simple resampling using linear interpolation."""
        if orig_sr == target_sr:
            return audio
        
        duration = len(audio) / orig_sr
        target_length = int(duration * target_sr)
        indices = np.linspace(0, len(audio) - 1, target_length)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
    
    def unload(self) -> None:
        """Unload the model from memory."""
        self._model = None
        self._loaded = False
    
    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._loaded


def test_engine(audio_file: Optional[str] = None) -> None:
    """
    Test the Whisper engine standalone.
    
    Args:
        audio_file: Optional path to a WAV file. If None, uses test data.
    """
    import wave
    
    print("Testing Whisper STT Engine...")
    
    config = STTConfig(model="medium", language="en")
    engine = WhisperEngine(config)
    
    print(f"Loading model: {config.model}")
    engine.load()
    print("Model loaded!")
    
    if audio_file:
        # Load from file
        with wave.open(audio_file, 'rb') as wf:
            sample_rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        
        print(f"Transcribing: {audio_file}")
        result = engine.transcribe(audio_data, sample_rate)
        
        print(f"\nResult:")
        print(f"  Text: {result.text}")
        print(f"  Confidence: {result.confidence:.2%}")
        print(f"  Duration: {result.duration_seconds:.2f}s")
        print(f"  Meets threshold: {result.meets_threshold(config.confidence_threshold)}")
    else:
        print("No audio file provided. Engine ready for transcription.")
    
    engine.unload()
    print("Engine unloaded.")


if __name__ == "__main__":
    import sys
    audio_file = sys.argv[1] if len(sys.argv) > 1 else None
    test_engine(audio_file)
