"""
JARVIS Test Configuration
-------------------------
Shared fixtures and configuration for all tests.

v0.8.0: Browser blocking for test isolation.
"""

import sys
import webbrowser
from pathlib import Path
import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# Test Isolation: Block Side Effects
# =============================================================================

@pytest.fixture(autouse=True)
def block_browser_open(monkeypatch):
    """
    Block webbrowser.open() during tests.
    
    This ensures:
    - Tests are hermetic (no external side effects)
    - Safari doesn't open during test runs
    - CI pipelines don't hang
    
    If something tries to open a browser, it raises RuntimeError.
    """
    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "webbrowser.open() is forbidden during tests. "
            "Wrap browser calls in a condition or mock them."
        )
    
    monkeypatch.setattr(webbrowser, "open", _blocked)
    monkeypatch.setattr(webbrowser, "open_new", _blocked)
    monkeypatch.setattr(webbrowser, "open_new_tab", _blocked)


@pytest.fixture(autouse=True)
def block_subprocess_open(monkeypatch):
    """
    Block subprocess.run() calls that would open applications.
    
    Specifically blocks:
    - ["open", "-a", ...] on macOS (app launcher)
    - ["start", ...] on Windows
    
    Returns a mock success instead of actually opening.
    """
    import subprocess
    
    _original_run = subprocess.run
    
    def _mock_run(args, *a, **kwargs):
        # Check if this is an "open" command
        if isinstance(args, list) and len(args) > 0:
            cmd = args[0]
            if cmd in ("open", "start"):
                # Return mock success - don't actually open
                class MockResult:
                    returncode = 0
                    stdout = b""
                    stderr = b""
                return MockResult()
        
        # Allow other subprocess calls
        return _original_run(args, *a, **kwargs)
    
    monkeypatch.setattr(subprocess, "run", _mock_run)



@pytest.fixture(scope="session")
def project_root():
    """Return the project root path."""
    return PROJECT_ROOT


@pytest.fixture(scope="function")
def mock_tool_schemas():
    """Standard tool schemas for testing."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "Get the current time",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_date",
                "description": "Get the current date",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "format": {"type": "string", "description": "Date format"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "open_application",
                "description": "Open an application",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "Application name"}
                    },
                    "required": ["app_name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_volume",
                "description": "Set system volume",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "integer", "description": "Volume level 0-100"}
                    },
                    "required": ["level"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List files in a directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "take_screenshot",
                "description": "Capture a screenshot",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "description": "Screen region"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "capture_camera",
                "description": "Capture from camera",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "analyze": {"type": "boolean", "description": "Analyze the image"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "schedule_task",
                "description": "Schedule a task",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Task name"},
                        "action": {"type": "string", "description": "Action to perform"},
                        "hour": {"type": "integer", "description": "Hour to execute"},
                        "minute": {"type": "integer", "description": "Minute to execute"}
                    },
                    "required": ["name", "action"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_scheduled_tasks",
                "description": "List scheduled tasks",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
    ]


@pytest.fixture(scope="function")
def mock_planner(mock_tool_schemas):
    """Create a mock LLM planner for testing."""
    from planner.llm_planner import MockLLMPlanner
    return MockLLMPlanner(tool_schemas=mock_tool_schemas)
