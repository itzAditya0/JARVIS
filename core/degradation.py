"""
Graceful Degradation
---------------------
Policy-driven failure handling for resilient operation.

v0.8.0: Reliability release.

Design:
- Strategies: FAIL_FAST, RETRY, FALLBACK, SKIP, PARTIAL
- Policies per tool/category
- Dependency-aware abort detection
- All exceptions → classified JARVISError
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set
import logging

from .errors import JARVISError, ErrorCategory
from tools.registry import PermissionLevel


class DegradationStrategy(Enum):
    """How to handle tool failures."""
    FAIL_FAST = auto()   # Return error immediately, abort plan
    RETRY = auto()       # Retry with backoff
    FALLBACK = auto()    # Use fallback tool
    SKIP = auto()        # Skip and continue plan
    PARTIAL = auto()     # Return partial result


@dataclass
class DegradationPolicy:
    """
    Policy for handling tool failures.
    
    Configurable per tool or category.
    """
    tool_name: str
    strategy: DegradationStrategy
    fallback_tool: Optional[str] = None
    max_retries: int = 2
    retry_delay: float = 1.0
    is_critical: bool = False  # If True, SKIP not allowed
    
    def allows_skip(self) -> bool:
        """Check if this tool can be skipped."""
        return not self.is_critical and self.strategy in {
            DegradationStrategy.SKIP,
            DegradationStrategy.PARTIAL
        }


@dataclass
class FailureBudget:
    """
    Track failures per turn to prevent runaway execution.
    
    Rules:
    - Max failures per turn
    - Max consecutive failures
    - Abort turn when budget exceeded
    """
    max_failures_per_turn: int = 3
    max_consecutive_failures: int = 2
    
    _total_failures: int = field(default=0, repr=False)
    _consecutive_failures: int = field(default=0, repr=False)
    _skipped_tools: Set[str] = field(default_factory=set, repr=False)
    
    def record_failure(self, tool_name: str) -> None:
        """Record a tool failure."""
        self._total_failures += 1
        self._consecutive_failures += 1
    
    def record_success(self) -> None:
        """Record a tool success (resets consecutive counter)."""
        self._consecutive_failures = 0
    
    def record_skip(self, tool_name: str) -> None:
        """Record a skipped tool for dependency tracking."""
        self._skipped_tools.add(tool_name)
    
    def should_abort(self) -> bool:
        """Check if turn should be aborted due to excessive failures."""
        return (
            self._total_failures >= self.max_failures_per_turn or
            self._consecutive_failures >= self.max_consecutive_failures
        )
    
    def is_dependency_skipped(self, dependencies: List[str]) -> bool:
        """
        Check if any dependency was skipped.
        
        If True, turn must abort to prevent silent correctness degradation.
        """
        return bool(self._skipped_tools.intersection(dependencies))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get failure budget statistics."""
        return {
            "total_failures": self._total_failures,
            "consecutive_failures": self._consecutive_failures,
            "skipped_tools": list(self._skipped_tools),
            "should_abort": self.should_abort(),
        }
    
    def reset(self) -> None:
        """Reset for new turn."""
        self._total_failures = 0
        self._consecutive_failures = 0
        self._skipped_tools.clear()


class DegradationManager:
    """
    Manages degradation policies for all tools.
    
    Provides default policies by permission level.
    """
    
    # Default strategies by permission level
    DEFAULT_STRATEGIES: Dict[PermissionLevel, DegradationStrategy] = {
        PermissionLevel.READ: DegradationStrategy.RETRY,
        PermissionLevel.WRITE: DegradationStrategy.FAIL_FAST,
        PermissionLevel.EXECUTE: DegradationStrategy.FAIL_FAST,
        PermissionLevel.NETWORK: DegradationStrategy.RETRY,
        PermissionLevel.ADMIN: DegradationStrategy.FAIL_FAST,
    }
    
    # Critical levels that should never be skipped
    CRITICAL_LEVELS: Set[PermissionLevel] = {
        PermissionLevel.WRITE,
        PermissionLevel.EXECUTE,
        PermissionLevel.ADMIN,
    }
    
    def __init__(self):
        self._policies: Dict[str, DegradationPolicy] = {}
        self._logger = logging.getLogger("jarvis.degradation")
    
    def get_policy(
        self,
        tool_name: str,
        permission_level: PermissionLevel
    ) -> DegradationPolicy:
        """Get degradation policy for a tool."""
        # Check for explicit policy
        if tool_name in self._policies:
            return self._policies[tool_name]
        
        # Generate default policy based on permission level
        strategy = self.DEFAULT_STRATEGIES.get(
            permission_level,
            DegradationStrategy.FAIL_FAST
        )
        
        is_critical = permission_level in self.CRITICAL_LEVELS
        
        return DegradationPolicy(
            tool_name=tool_name,
            strategy=strategy,
            is_critical=is_critical,
            max_retries=2 if strategy == DegradationStrategy.RETRY else 0,
        )
    
    def set_policy(self, policy: DegradationPolicy) -> None:
        """Set explicit policy for a tool."""
        self._policies[policy.tool_name] = policy
        self._logger.info(f"Set policy for {policy.tool_name}: {policy.strategy.name}")
    
    def should_skip(
        self,
        tool_name: str,
        permission_level: PermissionLevel,
        failure_budget: FailureBudget,
        dependencies: Optional[List[str]] = None
    ) -> tuple[bool, str]:
        """
        Determine if a tool should be skipped after failure.
        
        Returns (should_skip, reason).
        
        Dependency-Aware Abort Rule:
        If a skipped tool is a dependency for later steps, abort instead.
        """
        policy = self.get_policy(tool_name, permission_level)
        
        # Check if tool allows skipping
        if not policy.allows_skip():
            return False, f"Tool {tool_name} is critical and cannot be skipped"
        
        # Check if any dependencies were skipped
        if dependencies and failure_budget.is_dependency_skipped(dependencies):
            return False, "Dependency was skipped - must abort for correctness"
        
        # Check failure budget
        if failure_budget.should_abort():
            return False, "Failure budget exceeded - must abort turn"
        
        return True, f"Tool {tool_name} skipped per {policy.strategy.name} strategy"


def classify_exception(exception: Exception, tool_name: str = "") -> JARVISError:
    """
    Convert any exception to classified JARVISError.
    
    Enforcement Rule: All exceptions become JARVISError before returning to planner.
    """
    # Map known exception types to categories
    if isinstance(exception, TimeoutError):
        category = ErrorCategory.TIMEOUT_ERROR
    elif isinstance(exception, PermissionError):
        category = ErrorCategory.PERMISSION_ERROR
    elif isinstance(exception, (ConnectionError, OSError)):
        category = ErrorCategory.NETWORK_ERROR
    elif isinstance(exception, ValueError):
        category = ErrorCategory.VALIDATION_ERROR
    else:
        category = ErrorCategory.TOOL_FAILURE
    
    return JARVISError.from_exception(
        exception=exception,
        category=category,
        details={"tool": tool_name}
    )


# Global manager instance
_default_manager: Optional[DegradationManager] = None


def get_degradation_manager() -> DegradationManager:
    """Get or create the default degradation manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = DegradationManager()
    return _default_manager
