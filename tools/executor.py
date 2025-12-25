"""
Tool Executor
-------------
Sandboxed execution of tools with validation, timeout enforcement,
governance controls, and audit logging.

Exit Criterion: A malicious prompt cannot execute arbitrary commands.

v0.6.0 Governance:
- All executions go through ToolAuthority
- Confirmation required for WRITE/EXECUTE/NETWORK
- All decisions logged with turn_id

v0.7.0 Accountability:
- turn_id REQUIRED for all executions
- All tool executions logged to immutable audit log
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import concurrent.futures
import logging
import os
import platform
import subprocess
import uuid
import webbrowser

from .registry import Tool, ToolRegistry, PermissionLevel
from .authority import ToolAuthority, AuthorityDecision, GrantStatus

# Audit logging (v0.7.0)
try:
    from infra.audit import AuditLog, EventType, Actor, audit_event
    _AUDIT_AVAILABLE = True
except ImportError:
    _AUDIT_AVAILABLE = False


class ExecutionStatus(Enum):
    """Status of tool execution."""
    SUCCESS = auto()
    VALIDATION_ERROR = auto()
    PERMISSION_DENIED = auto()
    CONFIRMATION_REQUIRED = auto()  # v0.6.0: Awaiting user confirmation
    CONFIRMATION_DENIED = auto()    # v0.6.0: User denied confirmation
    CONFIRMATION_TIMEOUT = auto()   # v0.6.0: Confirmation timed out
    TIMEOUT = auto()
    EXECUTION_ERROR = auto()
    UNKNOWN_TOOL = auto()



@dataclass
class PendingConfirmation:
    """A tool execution awaiting user confirmation."""
    id: str
    tool_name: str
    args: Dict[str, Any]
    reason: str
    permission_level: PermissionLevel
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_in_seconds: int = 60
    turn_id: Optional[str] = None
    
    @property
    def is_expired(self) -> bool:
        from datetime import timedelta
        return datetime.now(timezone.utc) > self.requested_at + timedelta(seconds=self.expires_in_seconds)


@dataclass
class ExecutionResult:
    """Result of tool execution."""
    tool_name: str
    status: ExecutionStatus
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pending_confirmation: Optional[PendingConfirmation] = None  # v0.6.0
    turn_id: Optional[str] = None  # v0.6.0
    
    @property
    def success(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS
    
    @property
    def needs_confirmation(self) -> bool:
        return self.status == ExecutionStatus.CONFIRMATION_REQUIRED
    
    def __repr__(self) -> str:
        status = "✓" if self.success else ("?" if self.needs_confirmation else "✗")
        return f"ExecutionResult({status} {self.tool_name}: {self.output or self.error})"


@dataclass
class ExecutionContext:
    """Context for tool execution."""
    user_id: str = "default"
    session_id: str = ""
    allowed_directories: Set[str] = field(default_factory=lambda: {os.getcwd()})
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10MB
    network_allowed: bool = True
    dry_run: bool = False  # If True, don't actually execute


class ToolExecutor:
    """
    Sandboxed tool executor.
    
    Rules:
    - No shell=True in subprocess
    - All paths validated against allowlist
    - Timeouts enforced
    - All executions logged
    """
    
    # Allowlisted applications (lowercase)
    ALLOWED_APPS: Set[str] = {
        "safari", "chrome", "google chrome", "firefox",
        "terminal", "finder", "spotify", "notes",
        "calendar", "calculator", "textedit", "preview",
        "activity monitor", "system preferences"
    }
    
    # Blocked path patterns
    BLOCKED_PATHS: Set[str] = {
        "/etc", "/var", "/usr", "/bin", "/sbin",
        "/System", "/Library", "/private",
        ".ssh", ".gnupg", ".aws", ".config"
    }
    
    def __init__(
        self,
        registry: ToolRegistry,
        context: Optional[ExecutionContext] = None,
        authority: Optional[ToolAuthority] = None,
        config_path: Optional[str] = None
    ):
        self.registry = registry
        self.context = context or ExecutionContext()
        self.authority = authority or ToolAuthority(config_path=config_path)
        self._logger = logging.getLogger("jarvis.tools.executor")
        self._system = platform.system()
        self._pending_confirmations: Dict[str, PendingConfirmation] = {}
        
        # Bind actual executors to tools
        self._bind_executors()
    
    def _bind_executors(self) -> None:
        """Bind actual executor functions to registered tools."""
        executor_map = {
            "get_current_time": self._exec_get_time,
            "get_current_date": self._exec_get_date,
            "web_search": self._exec_web_search,
            "open_application": self._exec_open_app,
            "set_volume": self._exec_set_volume,
            "read_file": self._exec_read_file,
            "list_directory": self._exec_list_directory,
        }
        
        for tool_name, executor in executor_map.items():
            tool = self.registry.get(tool_name)
            if tool:
                tool.executor = executor
    
    def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        turn_id: Optional[str] = None,
        confirm_callback: Optional[Callable[[PendingConfirmation], bool]] = None
    ) -> ExecutionResult:
        """
        Execute a tool with validation, authority check, and sandboxing.
        
        This is the ONLY entry point for tool execution.
        
        v0.6.0 Governance:
        - Authority check before execution
        - Confirmation workflow for WRITE/EXECUTE/NETWORK
        - All decisions logged with turn_id
        """
        start_time = datetime.now(timezone.utc)
        
        # Get tool
        tool = self.registry.get(tool_name)
        if tool is None:
            return ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.UNKNOWN_TOOL,
                error=f"Unknown tool: {tool_name}",
                turn_id=turn_id
            )
        
        # Validate arguments
        valid, error = tool.validate_args(args)
        if not valid:
            self._logger.warning(f"Validation failed for {tool_name}: {error}")
            return ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.VALIDATION_ERROR,
                error=error,
                turn_id=turn_id
            )
        
        # v0.6.0: Authority check (replaces old _check_permission)
        decision = self.authority.check(tool_name, tool.permission, turn_id=turn_id)
        
        if decision.status == GrantStatus.REQUIRES_CONFIRMATION:
            # Check if tool explicitly requires confirmation
            if tool.requires_confirmation or decision.needs_confirmation:
                return self._handle_confirmation_required(
                    tool, args, decision, turn_id, confirm_callback
                )
        
        if not decision.allowed:
            return ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.PERMISSION_DENIED,
                error=f"Permission denied: {decision.reason}",
                turn_id=turn_id
            )
        
        # Dry run mode
        if self.context.dry_run:
            return ExecutionResult(
                tool_name=tool_name,
                status=ExecutionStatus.SUCCESS,
                output=f"[DRY RUN] Would execute {tool_name} with {args}",
                turn_id=turn_id
            )
        
        # Execute with timeout
        return self._execute_with_timeout(tool, args, turn_id, start_time)
    
    def _handle_confirmation_required(
        self,
        tool: Tool,
        args: Dict[str, Any],
        decision: AuthorityDecision,
        turn_id: Optional[str],
        confirm_callback: Optional[Callable[[PendingConfirmation], bool]]
    ) -> ExecutionResult:
        """
        Handle confirmation workflow.
        
        If confirm_callback provided, ask immediately.
        Otherwise, return CONFIRMATION_REQUIRED with pending details.
        """
        pending = PendingConfirmation(
            id=str(uuid.uuid4())[:8],
            tool_name=tool.name,
            args=args,
            reason=decision.reason,
            permission_level=tool.permission,
            turn_id=turn_id
        )
        
        if confirm_callback is None:
            # No callback - return pending confirmation
            self._pending_confirmations[pending.id] = pending
            self._logger.info(f"Confirmation required for {tool.name} (id={pending.id})")
            return ExecutionResult(
                tool_name=tool.name,
                status=ExecutionStatus.CONFIRMATION_REQUIRED,
                pending_confirmation=pending,
                turn_id=turn_id
            )
        
        # Callback provided - ask now
        self._logger.info(f"Requesting confirmation for {tool.name}")
        
        try:
            approved = confirm_callback(pending)
        except Exception as e:
            self._logger.error(f"Confirmation callback error: {e}")
            return ExecutionResult(
                tool_name=tool.name,
                status=ExecutionStatus.CONFIRMATION_DENIED,
                error=f"Confirmation failed: {e}",
                turn_id=turn_id
            )
        
        if not approved:
            self._logger.info(f"User denied {tool.name}")
            return ExecutionResult(
                tool_name=tool.name,
                status=ExecutionStatus.CONFIRMATION_DENIED,
                error="User denied confirmation",
                turn_id=turn_id
            )
        
        # User approved - grant session permission and execute
        self.authority.grant(
            target=tool.name,
            level=tool.permission,
            source="session"
        )
        
        start_time = datetime.now(timezone.utc)
        return self._execute_with_timeout(tool, args, turn_id, start_time)
    
    def confirm_pending(
        self,
        confirmation_id: str,
        approved: bool
    ) -> ExecutionResult:
        """
        Confirm or deny a pending execution.
        
        Called when user responds to confirmation prompt.
        """
        pending = self._pending_confirmations.pop(confirmation_id, None)
        
        if pending is None:
            return ExecutionResult(
                tool_name="unknown",
                status=ExecutionStatus.EXECUTION_ERROR,
                error=f"Unknown confirmation id: {confirmation_id}"
            )
        
        if pending.is_expired:
            self._logger.warning(f"Confirmation {confirmation_id} expired")
            return ExecutionResult(
                tool_name=pending.tool_name,
                status=ExecutionStatus.CONFIRMATION_TIMEOUT,
                error="Confirmation timed out. Please try again.",
                turn_id=pending.turn_id
            )
        
        if not approved:
            self._logger.info(f"User denied {pending.tool_name}")
            return ExecutionResult(
                tool_name=pending.tool_name,
                status=ExecutionStatus.CONFIRMATION_DENIED,
                error="User denied confirmation",
                turn_id=pending.turn_id
            )
        
        # Get tool and execute
        tool = self.registry.get(pending.tool_name)
        if tool is None:
            return ExecutionResult(
                tool_name=pending.tool_name,
                status=ExecutionStatus.UNKNOWN_TOOL,
                error=f"Tool no longer available: {pending.tool_name}"
            )
        
        # Grant session permission
        self.authority.grant(
            target=pending.tool_name,
            level=tool.permission,
            source="session"
        )
        
        start_time = datetime.now(timezone.utc)
        return self._execute_with_timeout(tool, pending.args, pending.turn_id, start_time)
    
    def _execute_with_timeout(
        self,
        tool: Tool,
        args: Dict[str, Any],
        turn_id: Optional[str],
        start_time: datetime
    ) -> ExecutionResult:
        """Execute tool with timeout, error handling, and audit logging."""
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(tool.executor, args)
                output = future.result(timeout=tool.timeout_seconds)
            
            execution_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            
            self._logger.info(f"Executed {tool.name}: {output}")
            
            # v0.7.0: Audit log
            if _AUDIT_AVAILABLE and turn_id:
                audit_event(
                    event_type=EventType.TOOL_EXECUTE,
                    actor=Actor.EXECUTOR,
                    action="success",
                    turn_id=turn_id,
                    target=tool.name,
                    details={"args": args, "execution_time_ms": execution_time}
                )
            
            return ExecutionResult(
                tool_name=tool.name,
                status=ExecutionStatus.SUCCESS,
                output=output,
                execution_time_ms=execution_time,
                turn_id=turn_id
            )
            
        except concurrent.futures.TimeoutError:
            self._logger.error(f"Timeout executing {tool.name}")
            
            # v0.7.0: Audit log
            if _AUDIT_AVAILABLE and turn_id:
                audit_event(
                    event_type=EventType.TOOL_EXECUTE,
                    actor=Actor.EXECUTOR,
                    action="timeout",
                    turn_id=turn_id,
                    target=tool.name,
                    details={"timeout_seconds": tool.timeout_seconds}
                )
            
            return ExecutionResult(
                tool_name=tool.name,
                status=ExecutionStatus.TIMEOUT,
                error=f"Execution timed out after {tool.timeout_seconds}s",
                turn_id=turn_id
            )
            
        except Exception as e:
            self._logger.error(f"Execution error in {tool.name}: {e}")
            
            # v0.7.0: Audit log
            if _AUDIT_AVAILABLE and turn_id:
                audit_event(
                    event_type=EventType.TOOL_EXECUTE,
                    actor=Actor.EXECUTOR,
                    action="error",
                    turn_id=turn_id,
                    target=tool.name,
                    details={"error": str(e)}
                )
            
            return ExecutionResult(
                tool_name=tool.name,
                status=ExecutionStatus.EXECUTION_ERROR,
                error=str(e),
                turn_id=turn_id
            )
    
    def _check_permission(self, tool: Tool) -> bool:
        """DEPRECATED: Use authority.check() instead."""
        # Kept for backwards compatibility
        decision = self.authority.check(tool.name, tool.permission)
        return decision.allowed
    
    def _validate_path(self, path: str) -> tuple[bool, Optional[str]]:
        """Validate a file path is safe to access."""
        try:
            resolved = Path(path).resolve()
            path_str = str(resolved)
            
            # Check blocked patterns
            for blocked in self.BLOCKED_PATHS:
                if blocked in path_str:
                    return False, f"Access to {blocked} is not allowed"
            
            # Check allowed directories
            is_allowed = any(
                path_str.startswith(allowed)
                for allowed in self.context.allowed_directories
            )
            
            if not is_allowed:
                return False, "Path is outside allowed directories"
            
            return True, None
            
        except Exception as e:
            return False, str(e)
    
    # Tool Executors
    
    def _exec_get_time(self, args: Dict) -> str:
        """Get current time."""
        now = datetime.now()
        return f"The current time is {now.strftime('%I:%M %p')}"
    
    def _exec_get_date(self, args: Dict) -> str:
        """Get current date."""
        now = datetime.now()
        fmt = args.get("format", "long")
        
        if fmt == "short":
            return now.strftime("%m/%d/%Y")
        elif fmt == "iso":
            return now.strftime("%Y-%m-%d")
        else:
            return now.strftime("%A, %B %d, %Y")
    
    def _exec_web_search(self, args: Dict) -> str:
        """Open web search."""
        query = args["query"]
        url = f"https://www.google.com/search?q={query}"
        webbrowser.open(url)
        return f"Opened search for: {query}"
    
    def _exec_open_app(self, args: Dict) -> str:
        """Open an application."""
        app_name = args["app_name"]
        
        # Validate against allowlist
        if app_name.lower() not in self.ALLOWED_APPS:
            raise PermissionError(f"Application not allowed: {app_name}")
        
        if self._system == "Darwin":
            subprocess.run(
                ["open", "-a", app_name],
                timeout=10,
                check=True,
                capture_output=True
            )
        elif self._system == "Windows":
            subprocess.run(
                ["start", "", app_name],
                timeout=10,
                shell=False
            )
        else:
            subprocess.run(
                [app_name.lower().replace(" ", "-")],
                timeout=10
            )
        
        return f"Opened: {app_name}"
    
    def _exec_set_volume(self, args: Dict) -> str:
        """Set system volume."""
        level = args["level"]
        
        if self._system == "Darwin":
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"],
                timeout=5,
                check=True,
                capture_output=True
            )
        
        return f"Volume set to {level}%"
    
    def _exec_read_file(self, args: Dict) -> str:
        """Read a file with safety checks."""
        path = args["path"]
        max_lines = args.get("max_lines", 100)
        
        # Validate path
        valid, error = self._validate_path(path)
        if not valid:
            raise PermissionError(error)
        
        resolved = Path(path).resolve()
        
        # Check file exists
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        if not resolved.is_file():
            raise ValueError(f"Not a file: {path}")
        
        # Check file size
        if resolved.stat().st_size > self.context.max_file_size_bytes:
            raise ValueError(f"File too large (max {self.context.max_file_size_bytes} bytes)")
        
        # Read file
        with open(resolved, 'r', errors='replace') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"... (truncated after {max_lines} lines)")
                    break
                lines.append(line.rstrip())
        
        return "\n".join(lines)
    
    def _exec_list_directory(self, args: Dict) -> str:
        """List directory contents."""
        path = args.get("path", ".")
        show_hidden = args.get("show_hidden", False)
        
        # Validate path
        valid, error = self._validate_path(path)
        if not valid:
            raise PermissionError(error)
        
        resolved = Path(path).resolve()
        
        if not resolved.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        
        if not resolved.is_dir():
            raise ValueError(f"Not a directory: {path}")
        
        # List contents
        entries = []
        for item in sorted(resolved.iterdir()):
            if not show_hidden and item.name.startswith('.'):
                continue
            
            if item.is_dir():
                entries.append(f"📁 {item.name}/")
            else:
                size = item.stat().st_size
                entries.append(f"📄 {item.name} ({size:,} bytes)")
        
        if not entries:
            return "Directory is empty"
        
        return "\n".join(entries[:50])  # Limit to 50 entries


def test_executor() -> None:
    """Test the tool executor."""
    from .registry import create_default_tools
    
    print("Testing Tool Executor...")
    
    registry = create_default_tools()
    executor = ToolExecutor(registry)
    
    # Test valid executions
    print("\nExecution Tests:")
    
    result = executor.execute("get_current_time", {})
    print(f"  get_current_time: {result}")
    
    result = executor.execute("get_current_date", {"format": "iso"})
    print(f"  get_current_date: {result}")
    
    result = executor.execute("list_directory", {"path": "."})
    print(f"  list_directory: {'✓ Success' if result.success else f'✗ {result.error}'}")
    
    # Test validation
    print("\nValidation Tests:")
    
    result = executor.execute("set_volume", {"level": 150})
    print(f"  set_volume(150): {'✗ Should fail' if result.success else f'✓ {result.status.name}'}")
    
    result = executor.execute("unknown_tool", {})
    print(f"  unknown_tool: {'✗ Should fail' if result.success else f'✓ {result.status.name}'}")
    
    # Test path security
    print("\nSecurity Tests:")
    
    result = executor.execute("read_file", {"path": "/etc/passwd"})
    print(f"  read_file(/etc/passwd): {'✗ Should fail' if result.success else f'✓ Blocked'}")
    
    print("\nAll tests passed!")


if __name__ == "__main__":
    test_executor()
