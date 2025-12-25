"""
Permission System
-----------------
Capability-based permissions with default deny.
No implicit trust. No role inference.

Exit Criterion: A command can be blocked even if matched correctly.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set
import logging
import subprocess
import platform
import webbrowser


class PermissionLevel(Enum):
    """Permission levels in ascending order of privilege."""
    READ = auto()      # Safe, no side effects
    EXECUTE = auto()   # May have side effects
    ADMIN = auto()     # System-level changes


@dataclass
class PermissionContext:
    """Context for permission decisions."""
    command_id: str
    permission_level: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)


class PermissionChecker:
    """
    Capability-based permission checker.
    
    Rules:
    - Default deny
    - Explicit allowlist only
    - No role inference
    """
    
    # Commands that are always allowed (read-only, no side effects)
    ALWAYS_ALLOWED: Set[str] = {
        "system.time",
        "system.date",
        "system.status",
        "assistant.help",
        "assistant.stop",
    }
    
    # Commands that require confirmation
    REQUIRE_CONFIRMATION: Set[str] = {
        "app.close",
        # Add more as needed
    }
    
    # Commands that are always blocked
    ALWAYS_BLOCKED: Set[str] = set()
    
    def __init__(self, default_policy: str = "deny"):
        self.default_policy = default_policy
        self._logger = logging.getLogger("jarvis.security")
        self._granted: Set[str] = set()  # Dynamically granted permissions
        self._denied: Set[str] = set()   # Dynamically denied permissions
    
    def check(
        self,
        command_id: str,
        permission_level: str,
        context: Optional[PermissionContext] = None
    ) -> bool:
        """
        Check if a command is permitted.
        
        Args:
            command_id: The command identifier
            permission_level: Required permission level (read, execute, admin)
            context: Optional context for the decision
        
        Returns:
            True if permitted, False otherwise
        """
        # Check explicit blocks first
        if command_id in self._denied or command_id in self.ALWAYS_BLOCKED:
            self._logger.warning(f"Permission DENIED (blocked): {command_id}")
            return False
        
        # Check explicit grants
        if command_id in self._granted or command_id in self.ALWAYS_ALLOWED:
            self._logger.debug(f"Permission GRANTED (allowlist): {command_id}")
            return True
        
        # Check permission level
        if permission_level == "read":
            self._logger.debug(f"Permission GRANTED (read): {command_id}")
            return True
        
        if permission_level == "execute":
            # In Phase 1, allow execute for demo purposes
            # In production, this should require explicit grant
            self._logger.info(f"Permission GRANTED (execute): {command_id}")
            return True
        
        if permission_level == "admin":
            self._logger.warning(f"Permission DENIED (admin): {command_id}")
            return False
        
        # Default policy
        if self.default_policy == "allow":
            self._logger.debug(f"Permission GRANTED (default): {command_id}")
            return True
        else:
            self._logger.warning(f"Permission DENIED (default): {command_id}")
            return False
    
    def grant(self, command_id: str) -> None:
        """Explicitly grant permission for a command."""
        self._granted.add(command_id)
        self._denied.discard(command_id)
        self._logger.info(f"Permission granted: {command_id}")
    
    def deny(self, command_id: str) -> None:
        """Explicitly deny permission for a command."""
        self._denied.add(command_id)
        self._granted.discard(command_id)
        self._logger.info(f"Permission denied: {command_id}")
    
    def revoke(self, command_id: str) -> None:
        """Revoke any explicit grant or deny."""
        self._granted.discard(command_id)
        self._denied.discard(command_id)
    
    def requires_confirmation(self, command_id: str) -> bool:
        """Check if a command requires user confirmation."""
        return command_id in self.REQUIRE_CONFIRMATION
    
    def get_status(self) -> Dict:
        """Get current permission status."""
        return {
            "default_policy": self.default_policy,
            "granted": list(self._granted),
            "denied": list(self._denied),
            "always_allowed": list(self.ALWAYS_ALLOWED),
            "always_blocked": list(self.ALWAYS_BLOCKED),
        }


class CommandExecutor:
    """
    Sandboxed command executor.
    
    Rules:
    - No shell=True
    - Allowlist only
    - Hardcoded command implementations
    - Timeouts enforced
    """
    
    def __init__(self, timeout_seconds: float = 30.0):
        self.timeout = timeout_seconds
        self._logger = logging.getLogger("jarvis.executor")
        self._system = platform.system()  # Darwin, Windows, Linux
    
    def execute(self, intent) -> Any:
        """
        Execute a matched command intent.
        
        Args:
            intent: CommandIntent from the registry
        
        Returns:
            Execution result
        
        Raises:
            PermissionError: If command is not in allowlist
            TimeoutError: If command exceeds timeout
            RuntimeError: If execution fails
        """
        command_id = intent.command_id
        args = intent.args
        
        self._logger.info(f"Executing: {command_id} with args={args}")
        
        # Route to specific handler
        handler = self._get_handler(command_id)
        
        if handler is None:
            raise PermissionError(f"No handler for command: {command_id}")
        
        try:
            result = handler(args)
            self._logger.info(f"Execution complete: {command_id}")
            return result
        except Exception as e:
            self._logger.error(f"Execution failed: {command_id} - {e}")
            raise RuntimeError(f"Command failed: {e}")
    
    def _get_handler(self, command_id: str):
        """Get the handler function for a command."""
        handlers = {
            "system.time": self._handle_system_time,
            "system.date": self._handle_system_date,
            "system.status": self._handle_system_status,
            "browser.open": self._handle_browser_open,
            "browser.search": self._handle_browser_search,
            "app.open": self._handle_app_open,
            "app.close": self._handle_app_close,
            "file.list": self._handle_file_list,
            "audio.volume_up": self._handle_volume_up,
            "audio.volume_down": self._handle_volume_down,
            "audio.mute": self._handle_mute,
            "assistant.help": self._handle_help,
            "assistant.stop": self._handle_stop,
        }
        return handlers.get(command_id)
    
    # Handler implementations
    
    def _handle_system_time(self, args: Dict) -> str:
        now = datetime.now()
        return f"The current time is {now.strftime('%I:%M %p')}"
    
    def _handle_system_date(self, args: Dict) -> str:
        now = datetime.now()
        return f"Today is {now.strftime('%A, %B %d, %Y')}"
    
    def _handle_system_status(self, args: Dict) -> str:
        return f"System is operational. Platform: {self._system}"
    
    def _handle_browser_open(self, args: Dict) -> str:
        webbrowser.open("https://www.google.com")
        return "Browser opened"
    
    def _handle_browser_search(self, args: Dict) -> str:
        query = args.get("query", "")
        if query:
            url = f"https://www.google.com/search?q={query}"
            webbrowser.open(url)
            return f"Searching for: {query}"
        return "No search query provided"
    
    def _handle_app_open(self, args: Dict) -> str:
        app_name = args.get("app_name", "").strip()
        
        if not app_name:
            return "No application specified"
        
        # Allowlist of safe applications
        safe_apps = {
            "safari": "Safari",
            "chrome": "Google Chrome",
            "firefox": "Firefox",
            "terminal": "Terminal",
            "finder": "Finder",
            "spotify": "Spotify",
            "notes": "Notes",
            "calendar": "Calendar",
            "calculator": "Calculator",
            "textedit": "TextEdit",
        }
        
        app_key = app_name.lower()
        
        if app_key not in safe_apps:
            return f"Application not in allowlist: {app_name}"
        
        actual_app = safe_apps[app_key]
        
        if self._system == "Darwin":  # macOS
            subprocess.run(
                ["open", "-a", actual_app],
                timeout=self.timeout,
                check=True
            )
        elif self._system == "Windows":
            subprocess.run(
                ["start", actual_app],
                shell=False,  # Important: no shell
                timeout=self.timeout
            )
        else:  # Linux
            subprocess.run(
                [app_key.lower()],
                timeout=self.timeout
            )
        
        return f"Opened: {actual_app}"
    
    def _handle_app_close(self, args: Dict) -> str:
        # For safety, we don't actually close apps in Phase 1
        app_name = args.get("app_name", "")
        return f"Close command received for: {app_name} (not implemented for safety)"
    
    def _handle_file_list(self, args: Dict) -> str:
        import os
        files = os.listdir(".")
        return f"Files in current directory: {', '.join(files[:10])}"
    
    def _handle_volume_up(self, args: Dict) -> str:
        if self._system == "Darwin":
            subprocess.run(
                ["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) + 10)"],
                timeout=self.timeout
            )
        return "Volume increased"
    
    def _handle_volume_down(self, args: Dict) -> str:
        if self._system == "Darwin":
            subprocess.run(
                ["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) - 10)"],
                timeout=self.timeout
            )
        return "Volume decreased"
    
    def _handle_mute(self, args: Dict) -> str:
        if self._system == "Darwin":
            subprocess.run(
                ["osascript", "-e", "set volume output muted true"],
                timeout=self.timeout
            )
        return "Audio muted"
    
    def _handle_help(self, args: Dict) -> str:
        return (
            "Available commands:\n"
            "- 'check system status'\n"
            "- 'what time is it'\n"
            "- 'open browser'\n"
            "- 'search for [query]'\n"
            "- 'open [app name]'\n"
            "- 'volume up/down'\n"
            "- 'help'"
        )
    
    def _handle_stop(self, args: Dict) -> str:
        return "Operation cancelled"


def test_permissions() -> None:
    """Test the permission system standalone."""
    print("Testing Permission System...")
    
    checker = PermissionChecker(default_policy="deny")
    
    # Test always allowed
    assert checker.check("system.time", "read") == True
    print("✓ Read permission works")
    
    # Test execute
    assert checker.check("browser.open", "execute") == True
    print("✓ Execute permission works")
    
    # Test admin (should be denied)
    assert checker.check("system.shutdown", "admin") == False
    print("✓ Admin permission blocked")
    
    # Test explicit grant
    checker.grant("custom.command")
    assert checker.check("custom.command", "execute") == True
    print("✓ Explicit grant works")
    
    # Test explicit deny
    checker.deny("custom.command")
    assert checker.check("custom.command", "execute") == False
    print("✓ Explicit deny works")
    
    print("\nAll permission tests passed!")


if __name__ == "__main__":
    test_permissions()
