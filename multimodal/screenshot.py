"""
Screenshot Capture and Analysis
-------------------------------
Screen capture and optional vision analysis.
All captures are user-initiated - no background monitoring.

Rules:
- No background screen monitoring
- All captures explicitly triggered
- Vision analysis optional (requires API)
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import base64
import io
import logging
import os
import subprocess
import tempfile


@dataclass
class ScreenRegion:
    """Define a region of the screen."""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    
    @property
    def is_full_screen(self) -> bool:
        return self.width == 0 and self.height == 0
    
    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@dataclass
class Screenshot:
    """A captured screenshot."""
    path: Path
    timestamp: datetime
    region: Optional[ScreenRegion] = None
    width: int = 0
    height: int = 0
    
    def to_base64(self) -> str:
        """Convert to base64 for API calls."""
        with open(self.path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def get_bytes(self) -> bytes:
        """Get raw image bytes."""
        with open(self.path, 'rb') as f:
            return f.read()
    
    def delete(self) -> None:
        """Delete the screenshot file."""
        if self.path.exists():
            self.path.unlink()


class ScreenCapture:
    """
    Screen capture utility.
    Uses native macOS screencapture or cross-platform pillow.
    """
    
    def __init__(self, output_dir: Optional[str] = None):
        if output_dir:
            self._output_dir = Path(output_dir)
        else:
            # Default to Desktop/JARVIS/Screenshots
            self._output_dir = Path.home() / "Desktop" / "JARVIS" / "Screenshots"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("jarvis.multimodal.screenshot")
        self._use_native = self._check_native_available()
    
    def _check_native_available(self) -> bool:
        """Check if native screencapture is available (macOS)."""
        import platform
        if platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    ["which", "screencapture"],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            except Exception:
                pass
        return False
    
    def capture(
        self,
        region: Optional[ScreenRegion] = None,
        filename: Optional[str] = None
    ) -> Optional[Screenshot]:
        """
        Capture a screenshot.
        
        Args:
            region: Optional region to capture (full screen if None)
            filename: Optional filename (auto-generated if None)
        
        Returns:
            Screenshot object or None on failure
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
        
        output_path = self._output_dir / filename
        
        try:
            if self._use_native:
                success = self._capture_native(output_path, region)
            else:
                success = self._capture_pillow(output_path, region)
            
            if success and output_path.exists():
                self._logger.info(f"Screenshot captured: {output_path}")
                return Screenshot(
                    path=output_path,
                    timestamp=datetime.now(),
                    region=region
                )
            else:
                self._logger.error("Screenshot capture failed")
                return None
                
        except Exception as e:
            self._logger.error(f"Screenshot error: {e}")
            return None
    
    def _capture_native(
        self,
        output_path: Path,
        region: Optional[ScreenRegion] = None
    ) -> bool:
        """Capture using macOS screencapture."""
        args = ["screencapture", "-x"]  # -x = no sound
        
        if region and not region.is_full_screen:
            # -R x,y,w,h for region capture
            args.extend([
                "-R",
                f"{region.x},{region.y},{region.width},{region.height}"
            ])
        
        args.append(str(output_path))
        
        result = subprocess.run(args, capture_output=True)
        return result.returncode == 0
    
    def _capture_pillow(
        self,
        output_path: Path,
        region: Optional[ScreenRegion] = None
    ) -> bool:
        """Capture using Pillow (cross-platform)."""
        try:
            from PIL import ImageGrab
            
            if region and not region.is_full_screen:
                bbox = (
                    region.x,
                    region.y,
                    region.x + region.width,
                    region.y + region.height
                )
                img = ImageGrab.grab(bbox=bbox)
            else:
                img = ImageGrab.grab()
            
            img.save(output_path)
            return True
            
        except ImportError:
            self._logger.error("Pillow not available for screenshot")
            return False
        except Exception as e:
            self._logger.error(f"Pillow capture error: {e}")
            return False
    
    def capture_window(self, window_name: str) -> Optional[Screenshot]:
        """Capture a specific window by name (macOS only)."""
        if not self._use_native:
            self._logger.warning("Window capture only available on macOS")
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self._output_dir / f"window_{timestamp}.png"
        
        # Use screencapture with window selection
        result = subprocess.run(
            ["screencapture", "-x", "-l", window_name, str(output_path)],
            capture_output=True
        )
        
        if result.returncode == 0 and output_path.exists():
            return Screenshot(
                path=output_path,
                timestamp=datetime.now()
            )
        return None
    
    def cleanup_old(self, max_age_hours: int = 24) -> int:
        """Delete screenshots older than max_age_hours."""
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        deleted = 0
        
        for file in self._output_dir.glob("*.png"):
            try:
                mtime = datetime.fromtimestamp(file.stat().st_mtime)
                if mtime < cutoff:
                    file.unlink()
                    deleted += 1
            except Exception:
                pass
        
        if deleted:
            self._logger.info(f"Cleaned up {deleted} old screenshots")
        
        return deleted


class ScreenAnalyzer:
    """
    Analyze screenshots using vision models.
    Requires Gemini API with vision capabilities.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._logger = logging.getLogger("jarvis.multimodal.analyzer")
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
        screenshot: Screenshot,
        prompt: str = "Describe what you see in this screenshot."
    ) -> Optional[str]:
        """
        Analyze a screenshot using vision model.
        
        Args:
            screenshot: Screenshot to analyze
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
            
            # Load image
            image = PIL.Image.open(screenshot.path)
            
            # Send to Gemini
            response = client.generate_content([prompt, image])
            
            return response.text
            
        except Exception as e:
            self._logger.error(f"Vision analysis error: {e}")
            return None
    
    def find_element(
        self,
        screenshot: Screenshot,
        description: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find a UI element by description.
        Returns approximate location if found.
        """
        prompt = f"""Look at this screenshot and find: {description}

If found, respond with JSON:
{{"found": true, "description": "...", "location": "top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right"}}

If not found:
{{"found": false, "reason": "..."}}

Respond ONLY with JSON."""
        
        result = self.analyze(screenshot, prompt)
        
        if result:
            try:
                import json
                # Extract JSON from response
                start = result.find('{')
                end = result.rfind('}') + 1
                if start >= 0 and end > start:
                    return json.loads(result[start:end])
            except Exception:
                pass
        
        return None
    
    def extract_text(self, screenshot: Screenshot) -> Optional[str]:
        """Extract visible text from screenshot (OCR-like)."""
        prompt = """Extract all visible text from this screenshot.
List each distinct text element on a new line.
Only include the actual text, no descriptions."""
        
        return self.analyze(screenshot, prompt)


def test_screenshot() -> None:
    """Test screenshot capture."""
    print("Testing Screenshot Capture...")
    
    capture = ScreenCapture()
    
    # Test full screen capture
    print("\nCapturing full screen...")
    screenshot = capture.capture()
    
    if screenshot:
        print(f"✓ Captured: {screenshot.path}")
        print(f"  Size: {screenshot.path.stat().st_size} bytes")
        
        # Cleanup
        screenshot.delete()
        print("  Cleaned up")
    else:
        print("✗ Capture failed")
    
    # Test region capture
    print("\nCapturing region (100x100 at 0,0)...")
    region = ScreenRegion(x=0, y=0, width=100, height=100)
    screenshot = capture.capture(region=region)
    
    if screenshot:
        print(f"✓ Region captured: {screenshot.path}")
        screenshot.delete()
    else:
        print("✗ Region capture failed")
    
    print("\nAll tests complete!")


if __name__ == "__main__":
    test_screenshot()
