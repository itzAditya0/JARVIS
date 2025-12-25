"""
Circuit Breaker
----------------
Prevents cascading failures by isolating failing tools.

v0.8.0: Reliability release.

Design:
- Scoped per tool name (one breaker per tool)
- State machine: CLOSED → OPEN → HALF_OPEN → CLOSED
- Thread-safe state transitions
- Configurable thresholds

State Transitions:
- CLOSED: Normal operation, counting failures
- OPEN: Rejecting calls, waiting for recovery timeout
- HALF_OPEN: Testing with limited calls
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional, TypeVar
import logging
import threading

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = auto()      # Normal operation
    OPEN = auto()        # Failing, reject calls
    HALF_OPEN = auto()   # Testing recovery


class CircuitOpenError(Exception):
    """Raised when circuit is open and call is rejected."""
    
    def __init__(self, breaker_name: str, remaining_seconds: float):
        self.breaker_name = breaker_name
        self.remaining_seconds = remaining_seconds
        super().__init__(
            f"Circuit '{breaker_name}' is OPEN. "
            f"Retry in {remaining_seconds:.1f}s"
        )


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for tool execution.
    
    Scope: One breaker per tool name.
    
    Prevents cascading failures by:
    1. Counting consecutive failures
    2. Opening circuit after threshold
    3. Rejecting calls while open
    4. Testing recovery with half-open state
    """
    name: str  # Tool name - one breaker per tool
    failure_threshold: int = 5
    recovery_timeout: float = 30.0  # Seconds before half-open
    success_threshold: int = 2      # Successes in half-open to close
    
    # Internal state (not part of constructor signature)
    _state: CircuitState = field(default=CircuitState.CLOSED, repr=False)
    _failure_count: int = field(default=0, repr=False)
    _success_count: int = field(default=0, repr=False)
    _last_failure_time: Optional[datetime] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    
    def __post_init__(self):
        self._logger = logging.getLogger(f"jarvis.circuit.{self.name}")
    
    @property
    def state(self) -> CircuitState:
        """Get current state, checking for timeout transitions."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    self._logger.info(f"Circuit {self.name}: OPEN → HALF_OPEN")
            return self._state
    
    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN
    
    def _should_attempt_recovery(self) -> bool:
        """Check if recovery timeout has elapsed."""
        if self._last_failure_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout
    
    def _get_remaining_timeout(self) -> float:
        """Get seconds remaining before recovery attempt."""
        if self._last_failure_time is None:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - self._last_failure_time).total_seconds()
        return max(0.0, self.recovery_timeout - elapsed)
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute function with circuit breaker protection.
        
        Raises CircuitOpenError if circuit is open.
        """
        # Check state
        current_state = self.state
        
        if current_state == CircuitState.OPEN:
            raise CircuitOpenError(self.name, self._get_remaining_timeout())
        
        # Execute
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise
    
    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._logger.info(f"Circuit {self.name}: HALF_OPEN → CLOSED (recovered)")
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
    
    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now(timezone.utc)
            
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open returns to open
                self._state = CircuitState.OPEN
                self._logger.warning(f"Circuit {self.name}: HALF_OPEN → OPEN (failure during test)")
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._logger.warning(
                        f"Circuit {self.name}: CLOSED → OPEN "
                        f"(failures={self._failure_count})"
                    )
    
    def reset(self) -> None:
        """Force reset to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._logger.info(f"Circuit {self.name}: RESET → CLOSED")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.name,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure": self._last_failure_time.isoformat() if self._last_failure_time else None,
            }


class CircuitBreakerRegistry:
    """
    Registry of circuit breakers.
    
    One breaker per tool name, created on demand.
    """
    
    def __init__(
        self,
        default_failure_threshold: int = 5,
        default_recovery_timeout: float = 30.0,
        default_success_threshold: int = 2
    ):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
        self._default_failure_threshold = default_failure_threshold
        self._default_recovery_timeout = default_recovery_timeout
        self._default_success_threshold = default_success_threshold
        self._logger = logging.getLogger("jarvis.circuit.registry")
    
    def get(self, tool_name: str) -> CircuitBreaker:
        """Get or create circuit breaker for tool."""
        with self._lock:
            if tool_name not in self._breakers:
                self._breakers[tool_name] = CircuitBreaker(
                    name=tool_name,
                    failure_threshold=self._default_failure_threshold,
                    recovery_timeout=self._default_recovery_timeout,
                    success_threshold=self._default_success_threshold,
                )
                self._logger.debug(f"Created circuit breaker for {tool_name}")
            return self._breakers[tool_name]
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats for all breakers."""
        with self._lock:
            return {name: breaker.get_stats() for name, breaker in self._breakers.items()}
    
    def get_open_circuits(self) -> list[str]:
        """Get list of open circuit breaker names."""
        with self._lock:
            return [name for name, breaker in self._breakers.items() if breaker.is_open]
    
    def reset_all(self) -> int:
        """Reset all circuit breakers. Returns count."""
        with self._lock:
            count = len(self._breakers)
            for breaker in self._breakers.values():
                breaker.reset()
            return count


# Global registry instance
_default_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_registry() -> CircuitBreakerRegistry:
    """Get or create the default circuit breaker registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = CircuitBreakerRegistry()
    return _default_registry


def get_circuit_breaker(tool_name: str) -> CircuitBreaker:
    """Get circuit breaker for a tool."""
    return get_circuit_registry().get(tool_name)
