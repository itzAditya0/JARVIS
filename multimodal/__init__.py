# Multimodal module - Screenshot, camera, and event triggers
# Phase 4: Visual input and automation triggers

from .screenshot import ScreenCapture, ScreenAnalyzer, ScreenRegion
from .events import EventTrigger, EventManager, ScheduledTask, TimeSpec
from .camera import CameraCapture, CameraFrame, CameraAnalyzer, OPENCV_AVAILABLE

__all__ = [
    "ScreenCapture",
    "ScreenAnalyzer",
    "ScreenRegion",
    "EventTrigger",
    "EventManager",
    "ScheduledTask",
    "TimeSpec",
    "CameraCapture",
    "CameraFrame",
    "CameraAnalyzer",
    "OPENCV_AVAILABLE"
]
