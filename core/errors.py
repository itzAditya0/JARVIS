"""
Error Handling Module
---------------------
Typed errors with classification and retry logic.
No silent retries on hallucinations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Type
import logging
import traceback


class ErrorCategory(Enum):
    """Categories of errors for handling decisions."""
    TOOL_FAILURE = auto()       # Tool execution failed
    VALIDATION_ERROR = auto()   # Input validation failed
    LLM_FAILURE = auto()        # LLM API/parsing error
    LLM_HALLUCINATION = auto()  # LLM produced invalid output
    PERMISSION_ERROR = auto()   # Permission denied
    NETWORK_ERROR = auto()      # Network/API error
    TIMEOUT_ERROR = auto()      # Operation timed out
    SYSTEM_ERROR = auto()       # Internal system error
    USER_ERROR = auto()         # User input error


@dataclass
class JARVISError:
    """
    Structured error with metadata.
    
    Used for consistent error handling and reporting.
    """
    category: ErrorCategory
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.now)
    stack_trace: Optional[str] = None
    recoverable: bool = True
    
    @classmethod
    def from_exception(
        cls,
        exception: Exception,
        category: ErrorCategory,
        details: Optional[Dict] = None
    ) -> "JARVISError":
        """Create error from an exception."""
        return cls(
            category=category,
            message=str(exception),
            details=details,
            stack_trace=traceback.format_exc(),
            recoverable=category not in {
                ErrorCategory.SYSTEM_ERROR,
                ErrorCategory.LLM_HALLUCINATION
            }
        )
    
    def __repr__(self) -> str:
        return f"JARVISError({self.category.name}: {self.message})"


class RetryPolicy:
    """
    Retry policy for different error categories.
    
    Critical: No retries on LLM hallucinations!
    """
    
    # Maximum retries per error category
    MAX_RETRIES: Dict[ErrorCategory, int] = {
        ErrorCategory.TOOL_FAILURE: 2,
        ErrorCategory.VALIDATION_ERROR: 0,  # No retry - fix input
        ErrorCategory.LLM_FAILURE: 1,       # Retry once for API errors
        ErrorCategory.LLM_HALLUCINATION: 0, # NEVER retry hallucinations
        ErrorCategory.PERMISSION_ERROR: 0,  # No retry - needs grant
        ErrorCategory.NETWORK_ERROR: 3,     # Network can be flaky
        ErrorCategory.TIMEOUT_ERROR: 1,     # One retry for timeouts
        ErrorCategory.SYSTEM_ERROR: 0,      # No retry - needs fix
        ErrorCategory.USER_ERROR: 0,        # No retry - needs user fix
    }
    
    # Delay between retries (seconds)
    RETRY_DELAYS: Dict[ErrorCategory, float] = {
        ErrorCategory.TOOL_FAILURE: 1.0,
        ErrorCategory.LLM_FAILURE: 2.0,
        ErrorCategory.NETWORK_ERROR: 1.0,
        ErrorCategory.TIMEOUT_ERROR: 2.0,
    }
    
    @classmethod
    def should_retry(cls, error: JARVISError, attempt: int) -> bool:
        """Check if operation should be retried."""
        max_retries = cls.MAX_RETRIES.get(error.category, 0)
        return attempt < max_retries and error.recoverable
    
    @classmethod
    def get_delay(cls, error: JARVISError) -> float:
        """Get delay before retry in seconds."""
        return cls.RETRY_DELAYS.get(error.category, 1.0)


class ErrorHandler:
    """
    Central error handler with logging and recovery.
    """
    
    def __init__(self):
        self._logger = logging.getLogger("jarvis.errors")
        self._error_history: List[JARVISError] = []
        self._max_history = 100
    
    def handle(self, error: JARVISError) -> str:
        """
        Handle an error and return user-friendly message.
        """
        # Log error
        self._log_error(error)
        
        # Store in history
        self._error_history.append(error)
        if len(self._error_history) > self._max_history:
            self._error_history.pop(0)
        
        # Generate user message
        return self._get_user_message(error)
    
    def _log_error(self, error: JARVISError) -> None:
        """Log error with appropriate level."""
        level_map = {
            ErrorCategory.USER_ERROR: logging.INFO,
            ErrorCategory.VALIDATION_ERROR: logging.WARNING,
            ErrorCategory.PERMISSION_ERROR: logging.WARNING,
            ErrorCategory.LLM_HALLUCINATION: logging.WARNING,
            ErrorCategory.TOOL_FAILURE: logging.ERROR,
            ErrorCategory.LLM_FAILURE: logging.ERROR,
            ErrorCategory.NETWORK_ERROR: logging.ERROR,
            ErrorCategory.TIMEOUT_ERROR: logging.ERROR,
            ErrorCategory.SYSTEM_ERROR: logging.CRITICAL,
        }
        
        level = level_map.get(error.category, logging.ERROR)
        
        self._logger.log(
            level,
            f"{error.category.name}: {error.message}",
            extra={"details": error.details}
        )
        
        if error.stack_trace and level >= logging.ERROR:
            self._logger.debug(f"Stack trace:\n{error.stack_trace}")
    
    def _get_user_message(self, error: JARVISError) -> str:
        """Generate user-friendly error message."""
        messages = {
            ErrorCategory.TOOL_FAILURE: "The command couldn't be completed. Please try again.",
            ErrorCategory.VALIDATION_ERROR: "I couldn't understand that request. Please try rephrasing.",
            ErrorCategory.LLM_FAILURE: "I'm having trouble processing that. Please try again.",
            ErrorCategory.LLM_HALLUCINATION: "I got confused. Let me try a different approach.",
            ErrorCategory.PERMISSION_ERROR: "I don't have permission to do that.",
            ErrorCategory.NETWORK_ERROR: "I'm having trouble connecting. Please check your internet.",
            ErrorCategory.TIMEOUT_ERROR: "That took too long. Please try again.",
            ErrorCategory.SYSTEM_ERROR: "Something went wrong internally. Please try again later.",
            ErrorCategory.USER_ERROR: error.message,
        }
        
        return messages.get(error.category, "An error occurred.")
    
    def get_error_stats(self) -> Dict[str, int]:
        """Get error statistics."""
        stats = {}
        for error in self._error_history:
            key = error.category.name
            stats[key] = stats.get(key, 0) + 1
        return stats
    
    def clear_history(self) -> None:
        """Clear error history."""
        self._error_history.clear()


# Convenience functions

def create_tool_error(message: str, tool_name: str = "") -> JARVISError:
    """Create a tool failure error."""
    return JARVISError(
        category=ErrorCategory.TOOL_FAILURE,
        message=message,
        details={"tool": tool_name}
    )


def create_validation_error(message: str, field: str = "") -> JARVISError:
    """Create a validation error."""
    return JARVISError(
        category=ErrorCategory.VALIDATION_ERROR,
        message=message,
        details={"field": field}
    )


def create_llm_error(message: str, is_hallucination: bool = False) -> JARVISError:
    """Create an LLM error."""
    return JARVISError(
        category=ErrorCategory.LLM_HALLUCINATION if is_hallucination else ErrorCategory.LLM_FAILURE,
        message=message,
        recoverable=not is_hallucination
    )


def create_permission_error(message: str, command: str = "") -> JARVISError:
    """Create a permission error."""
    return JARVISError(
        category=ErrorCategory.PERMISSION_ERROR,
        message=message,
        details={"command": command},
        recoverable=False
    )
