"""
Camera Input Module
-------------------
OpenCV-based camera capture for visual input.
All captures are user-initiated - no background monitoring.

Rules:
- No background camera monitoring
- All captures explicitly triggered
- Privacy-first design
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import base64
import logging
import tempfile

# OpenCV is optional
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    cv2 = None
    OPENCV_AVAILABLE = False


@dataclass
class CameraFrame:
    """A captured camera frame."""
    path: Path
    timestamp: datetime
    width: int
    height: int
    camera_id: int
    
    def to_base64(self) -> str:
        """Convert to base64 for API calls."""
        with open(self.path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def get_bytes(self) -> bytes:
        """Get raw image bytes."""
        with open(self.path, 'rb') as f:
            return f.read()
    
    def delete(self) -> None:
        """Delete the frame file."""
        if self.path.exists():
            self.path.unlink()


class CameraCapture:
    """
    Camera capture utility using OpenCV.
    Captures single frames on demand - no continuous monitoring.
    """
    
    def __init__(
        self,
        camera_id: int = 0,
        output_dir: Optional[str] = None
    ):
        self._camera_id = camera_id
        if output_dir:
            self._output_dir = Path(output_dir)
        else:
            # Default to Desktop/JARVIS/Camera
            self._output_dir = Path.home() / "Desktop" / "JARVIS" / "Camera"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("jarvis.multimodal.camera")
        self._cap = None
    
    @property
    def is_available(self) -> bool:
        """Check if camera is available."""
        if not OPENCV_AVAILABLE:
            return False
        
        # Try to open camera briefly
        cap = cv2.VideoCapture(self._camera_id)
        available = cap.isOpened()
        cap.release()
        return available
    
    def capture(self, filename: Optional[str] = None) -> Optional[CameraFrame]:
        """
        Capture a single frame from the camera.
        
        Args:
            filename: Optional filename (auto-generated if None)
        
        Returns:
            CameraFrame object or None on failure
        """
        if not OPENCV_AVAILABLE:
            self._logger.error("OpenCV not available. Install with: pip install opencv-python")
            return None
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"camera_{timestamp}.jpg"
        
        output_path = self._output_dir / filename
        
        try:
            # Open camera
            cap = cv2.VideoCapture(self._camera_id)
            
            if not cap.isOpened():
                self._logger.error(f"Cannot open camera {self._camera_id}")
                return None
            
            # Warm up camera (some cameras need this)
            for _ in range(5):
                cap.read()
            
            # Capture frame
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                self._logger.error("Failed to capture frame")
                return None
            
            # Get dimensions
            height, width = frame.shape[:2]
            
            # Save frame
            cv2.imwrite(str(output_path), frame)
            
            self._logger.info(f"Camera frame captured: {output_path}")
            
            return CameraFrame(
                path=output_path,
                timestamp=datetime.now(),
                width=width,
                height=height,
                camera_id=self._camera_id
            )
            
        except Exception as e:
            self._logger.error(f"Camera capture error: {e}")
            return None
    
    def list_cameras(self) -> List[int]:
        """List available camera IDs."""
        if not OPENCV_AVAILABLE:
            return []
        
        available = []
        for i in range(10):  # Check first 10 camera IDs
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append(i)
                cap.release()
        
        return available
    
    def get_camera_info(self) -> Dict[str, Any]:
        """Get information about the current camera."""
        if not OPENCV_AVAILABLE:
            return {"available": False, "error": "OpenCV not installed"}
        
        cap = cv2.VideoCapture(self._camera_id)
        if not cap.isOpened():
            return {"available": False, "error": f"Cannot open camera {self._camera_id}"}
        
        info = {
            "available": True,
            "camera_id": self._camera_id,
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": cap.get(cv2.CAP_PROP_FPS),
        }
        
        cap.release()
        return info
    
    def cleanup_old(self, max_age_hours: int = 24) -> int:
        """Delete frames older than max_age_hours."""
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        deleted = 0
        
        for file in self._output_dir.glob("*.jpg"):
            try:
                mtime = datetime.fromtimestamp(file.stat().st_mtime)
                if mtime < cutoff:
                    file.unlink()
                    deleted += 1
            except Exception:
                pass
        
        if deleted:
            self._logger.info(f"Cleaned up {deleted} old camera frames")
        
        return deleted


class CameraAnalyzer:
    """
    Analyze camera frames using vision models.
    Requires Gemini API with vision capabilities.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        import os
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._logger = logging.getLogger("jarvis.multimodal.camera_analyzer")
        self._client = None
    
    def _get_client(self):
        """Get or create the Gemini client."""
        if self._client is None:
            try:
                import google.generativeai as genai
                
                if not self._api_key:
                    raise ValueError("Gemini API key not configured")
                
                genai.configure(api_key=self._api_key)
                self._client = genai.GenerativeModel("gemini-2.0-flash")
                
            except ImportError:
                raise ImportError("google-generativeai required for vision analysis")
        
        return self._client
    
    def analyze(
        self,
        frame: CameraFrame,
        prompt: str = "Describe what you see in this image."
    ) -> Optional[str]:
        """
        Analyze a camera frame using vision model.
        
        Args:
            frame: CameraFrame to analyze
            prompt: Question or instruction about the image
        
        Returns:
            Analysis text or None on failure
        """
        if not self._api_key:
            self._logger.warning("Vision analysis requires GEMINI_API_KEY")
            return None
        
        try:
            import PIL.Image
            
            client = self._get_client()
            image = PIL.Image.open(frame.path)
            response = client.generate_content([prompt, image])
            
            return response.text
            
        except Exception as e:
            self._logger.error(f"Vision analysis error: {e}")
            return None
    
    def detect_objects(self, frame: CameraFrame) -> Optional[List[str]]:
        """Detect objects in the frame."""
        prompt = """List the main objects visible in this image.
Return as a simple comma-separated list.
Example: person, laptop, coffee cup, desk"""
        
        result = self.analyze(frame, prompt)
        if result:
            return [obj.strip() for obj in result.split(',')]
        return None
    
    def read_text(self, frame: CameraFrame) -> Optional[str]:
        """Read any visible text in the frame (OCR)."""
        prompt = """Extract all visible text from this image.
List each distinct text element on a new line.
Only include the actual text, no descriptions."""
        
        return self.analyze(frame, prompt)


def test_camera() -> None:
    """Test camera capture."""
    print("Testing Camera Capture...")
    
    if not OPENCV_AVAILABLE:
        print("✗ OpenCV not installed. Install with: pip install opencv-python")
        return
    
    camera = CameraCapture()
    
    # List cameras
    cameras = camera.list_cameras()
    print(f"\nAvailable cameras: {cameras}")
    
    if not cameras:
        print("✗ No cameras found")
        return
    
    # Get camera info
    info = camera.get_camera_info()
    print(f"\nCamera info: {info}")
    
    if not info.get("available"):
        print("✗ Camera not available")
        return
    
    # Capture frame
    print("\nCapturing frame...")
    frame = camera.capture()
    
    if frame:
        print(f"✓ Frame captured: {frame.path}")
        print(f"  Size: {frame.width}x{frame.height}")
        print(f"  File size: {frame.path.stat().st_size} bytes")
        
        # Cleanup
        frame.delete()
        print("  Cleaned up")
    else:
        print("✗ Capture failed")
    
    print("\nAll tests complete!")


if __name__ == "__main__":
    test_camera()
