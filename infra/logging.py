"""
JARVIS Centralized Logging
--------------------------
Structured logging with turn_id propagation for full request traceability.

Design:
- Every user turn gets a unique turn_id
- turn_id propagates through: Planner -> Tools -> Database
- Supports both console (Rich) and file (JSON) output
- Clear severity discipline: INFO=state, WARNING=recoverable, ERROR=abort

Usage:
    from infra.logging import get_logger, TurnContext, log_turn_end
    
    logger = get_logger("jarvis.core")
    
    with TurnContext() as turn_id:
        logger.info("Processing user input", extra={"turn_id": turn_id})
        # ... processing ...
        log_turn_end(turn_id, success=True, tools_executed=2)
"""

import contextvars
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Optional, Callable

# Context variable for turn_id - thread-safe and async-safe
_turn_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "turn_id", default=None
)


def generate_turn_id() -> str:
    """Generate a unique turn ID."""
    return f"turn_{uuid.uuid4().hex[:12]}"


def get_turn_id() -> Optional[str]:
    """Get the current turn ID from context."""
    return _turn_id_var.get()


def set_turn_id(turn_id: str) -> contextvars.Token:
    """Set the current turn ID in context."""
    return _turn_id_var.set(turn_id)


def reset_turn_id(token: contextvars.Token) -> None:
    """Reset the turn ID to its previous value."""
    _turn_id_var.reset(token)


class TurnContext:
    """
    Context manager for turn scoping.
    
    Usage:
        with TurnContext() as turn_id:
            # All logs within this block will have turn_id
            logger.info("Processing...")
    """
    
    def __init__(self, turn_id: Optional[str] = None):
        self._turn_id = turn_id or generate_turn_id()
        self._token: Optional[contextvars.Token] = None
    
    def __enter__(self) -> str:
        self._token = set_turn_id(self._turn_id)
        return self._turn_id
    
    def __exit__(self, *args) -> None:
        if self._token is not None:
            reset_turn_id(self._token)


class TurnIdFilter(logging.Filter):
    """Logging filter that adds turn_id to every log record."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Add turn_id from context if not already present
        if not hasattr(record, "turn_id") or record.turn_id is None:
            record.turn_id = get_turn_id() or "-"
        return True


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured file logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "turn_id": getattr(record, "turn_id", "-"),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key in ["tool_name", "tool_args", "execution_time_ms", "success", "tools_executed"]:
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        
        return json.dumps(log_entry)


class RichConsoleHandler(logging.StreamHandler):
    """Console handler with Rich formatting (if available)."""
    
    def __init__(self):
        super().__init__(sys.stderr)
        self._rich_available = False
        
        try:
            from rich.console import Console
            from rich.logging import RichHandler
            self._rich_available = True
        except ImportError:
            pass
    
    def emit(self, record: logging.LogRecord) -> None:
        try:
            turn_id = getattr(record, "turn_id", "-")
            level_colors = {
                "DEBUG": "\033[36m",    # Cyan
                "INFO": "\033[32m",     # Green
                "WARNING": "\033[33m",  # Yellow
                "ERROR": "\033[31m",    # Red
                "CRITICAL": "\033[35m", # Magenta
            }
            reset = "\033[0m"
            
            level = record.levelname
            color = level_colors.get(level, "")
            
            # Format: [LEVEL] [turn_id] logger: message
            turn_str = f"[{turn_id}]" if turn_id != "-" else ""
            msg = f"{color}[{level:7}]{reset} {turn_str} {record.name}: {record.getMessage()}"
            
            print(msg, file=sys.stderr)
            
        except Exception:
            self.handleError(record)


class FileRotatingHandler(logging.FileHandler):
    """Simple file handler with size-based rotation."""
    
    MAX_BYTES = 10 * 1024 * 1024  # 10 MB
    BACKUP_COUNT = 3
    
    def __init__(self, filename: str, max_bytes: int = None, backup_count: int = None):
        self._base_path = Path(filename)
        self._max_bytes = max_bytes or self.MAX_BYTES
        self._backup_count = backup_count or self.BACKUP_COUNT
        
        # Ensure directory exists
        self._base_path.parent.mkdir(parents=True, exist_ok=True)
        
        super().__init__(str(self._base_path), mode="a", encoding="utf-8")
    
    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._base_path.exists() and self._base_path.stat().st_size > self._max_bytes:
                self._rotate()
        except Exception:
            pass
        
        super().emit(record)
    
    def _rotate(self) -> None:
        """Rotate log files."""
        self.close()
        
        # Shift existing backups
        for i in range(self._backup_count - 1, 0, -1):
            src = self._base_path.with_suffix(f".{i}.log")
            dst = self._base_path.with_suffix(f".{i + 1}.log")
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
        
        # Move current to .1
        if self._base_path.exists():
            backup = self._base_path.with_suffix(".1.log")
            if backup.exists():
                backup.unlink()
            self._base_path.rename(backup)
        
        # Reopen
        self.stream = open(str(self._base_path), mode="a", encoding="utf-8")


# Global configuration state
_logging_initialized = False
_log_file_path: Optional[Path] = None


def configure_logging(
    level: int = logging.INFO,
    log_dir: Optional[str] = None,
    console: bool = True,
    file: bool = True,
) -> None:
    """
    Configure the JARVIS logging system.
    
    Args:
        level: Logging level (default INFO)
        log_dir: Directory for log files (default: ./logs)
        console: Enable console output
        file: Enable file output
    """
    global _logging_initialized, _log_file_path
    
    if _logging_initialized:
        return
    
    root_logger = logging.getLogger("jarvis")
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    
    # Add turn_id filter
    turn_filter = TurnIdFilter()
    
    if console:
        console_handler = RichConsoleHandler()
        console_handler.setLevel(level)
        console_handler.addFilter(turn_filter)
        root_logger.addHandler(console_handler)
    
    if file:
        log_path = Path(log_dir) if log_dir else Path("logs")
        log_path.mkdir(parents=True, exist_ok=True)
        
        _log_file_path = log_path / "jarvis.log"
        
        file_handler = FileRotatingHandler(str(_log_file_path))
        file_handler.setLevel(logging.DEBUG)  # File gets everything
        file_handler.setFormatter(JSONFormatter())
        file_handler.addFilter(turn_filter)
        root_logger.addHandler(file_handler)
    
    _logging_initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the JARVIS namespace.
    
    Args:
        name: Logger name (will be prefixed with 'jarvis.' if not already)
    
    Returns:
        Configured logger
    """
    if not name.startswith("jarvis"):
        name = f"jarvis.{name}"
    
    return logging.getLogger(name)


def log_turn_end(
    turn_id: str,
    success: bool,
    tools_executed: int = 0,
    error: Optional[str] = None,
) -> None:
    """
    Log the end of a user turn with summary information.
    
    This is the TURN_END boundary event for post-mortems.
    
    Args:
        turn_id: The turn ID being completed
        success: Whether the turn completed successfully
        tools_executed: Number of tools executed
        error: Error message if unsuccessful
    """
    logger = get_logger("core.turn")
    
    extra = {
        "turn_id": turn_id,
        "success": success,
        "tools_executed": tools_executed,
    }
    
    if success:
        logger.info(
            f"TURN_END: success={success}, tools_executed={tools_executed}",
            extra=extra,
        )
    else:
        extra["error"] = error or "Unknown error"
        logger.error(
            f"TURN_END: success={success}, error={error or 'Unknown'}",
            extra=extra,
        )


def with_turn_context(func: Callable) -> Callable:
    """
    Decorator to wrap a function in a turn context.
    
    The wrapped function will receive turn_id as a keyword argument.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        with TurnContext() as turn_id:
            kwargs["turn_id"] = turn_id
            return func(*args, **kwargs)
    return wrapper


# Auto-configure on import with sensible defaults
# Can be reconfigured by calling configure_logging() again
if not _logging_initialized:
    configure_logging()
