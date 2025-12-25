"""
Circuit Breaker Tests
----------------------
Tests for v0.8.0 circuit breaker implementation.

Tests cover:
- State transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- Threshold enforcement
- Recovery timeout
- Thread safety
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import time
import threading

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.circuit_breaker import (
    CircuitBreaker, CircuitState, CircuitOpenError,
    CircuitBreakerRegistry, get_circuit_breaker
)


class TestCircuitBreakerState:
    """Tests for circuit breaker state transitions."""
    
    def test_initial_state_closed(self):
        """Circuit starts in CLOSED state."""
        cb = CircuitBreaker(name="test-tool")
        
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed
    
    def test_opens_after_threshold(self):
        """Circuit opens after failure threshold reached."""
        cb = CircuitBreaker(name="test-tool", failure_threshold=3)
        
        for _ in range(3):
            cb.record_failure()
        
        assert cb.state == CircuitState.OPEN
        assert cb.is_open
    
    def test_stays_closed_below_threshold(self):
        """Circuit stays closed below failure threshold."""
        cb = CircuitBreaker(name="test-tool", failure_threshold=5)
        
        for _ in range(4):
            cb.record_failure()
        
        assert cb.state == CircuitState.CLOSED
    
    def test_success_resets_failure_count(self):
        """Success resets failure count in CLOSED state."""
        cb = CircuitBreaker(name="test-tool", failure_threshold=3)
        
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        
        # Should still be closed (not 3 consecutive failures)
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerRecovery:
    """Tests for circuit breaker recovery."""
    
    def test_transitions_to_half_open(self):
        """Circuit transitions to HALF_OPEN after timeout."""
        cb = CircuitBreaker(
            name="test-tool",
            failure_threshold=2,
            recovery_timeout=0.1  # 100ms for testing
        )
        
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        time.sleep(0.15)
        
        assert cb.state == CircuitState.HALF_OPEN
    
    def test_half_open_to_closed_on_success(self):
        """Circuit closes after successes in HALF_OPEN."""
        cb = CircuitBreaker(
            name="test-tool",
            failure_threshold=2,
            recovery_timeout=0.01,
            success_threshold=2
        )
        
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        
        # Wait for HALF_OPEN
        time.sleep(0.02)
        _ = cb.state  # Trigger state check
        
        # Record successes
        cb.record_success()
        cb.record_success()
        
        assert cb.state == CircuitState.CLOSED
    
    def test_half_open_to_open_on_failure(self):
        """Circuit reopens on failure in HALF_OPEN."""
        cb = CircuitBreaker(
            name="test-tool",
            failure_threshold=2,
            recovery_timeout=0.01
        )
        
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        
        # Wait for HALF_OPEN
        time.sleep(0.02)
        _ = cb.state
        
        # Record failure
        cb.record_failure()
        
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerCall:
    """Tests for circuit breaker call() method."""
    
    def test_call_success(self):
        """Successful call returns result."""
        cb = CircuitBreaker(name="test-tool")
        
        def success_func():
            return "result"
        
        result = cb.call(success_func)
        assert result == "result"
    
    def test_call_failure_records(self):
        """Failed call records failure."""
        cb = CircuitBreaker(name="test-tool", failure_threshold=2)
        
        def fail_func():
            raise ValueError("test error")
        
        with pytest.raises(ValueError):
            cb.call(fail_func)
        
        stats = cb.get_stats()
        assert stats["failure_count"] == 1
    
    def test_call_rejected_when_open(self):
        """Call rejected when circuit is open."""
        cb = CircuitBreaker(name="test-tool", failure_threshold=2)
        
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        
        def any_func():
            return "should not execute"
        
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.call(any_func)
        
        assert exc_info.value.breaker_name == "test-tool"


class TestCircuitBreakerRegistry:
    """Tests for circuit breaker registry."""
    
    def test_creates_breaker_on_demand(self):
        """Registry creates breakers on first access."""
        registry = CircuitBreakerRegistry()
        
        cb = registry.get("new-tool")
        
        assert cb.name == "new-tool"
        assert cb.state == CircuitState.CLOSED
    
    def test_returns_same_breaker(self):
        """Registry returns same breaker for same tool."""
        registry = CircuitBreakerRegistry()
        
        cb1 = registry.get("my-tool")
        cb2 = registry.get("my-tool")
        
        assert cb1 is cb2
    
    def test_get_open_circuits(self):
        """Can list open circuits."""
        registry = CircuitBreakerRegistry(default_failure_threshold=2)
        
        cb1 = registry.get("tool-a")
        cb2 = registry.get("tool-b")
        
        cb1.record_failure()
        cb1.record_failure()  # Opens
        
        open_circuits = registry.get_open_circuits()
        
        assert "tool-a" in open_circuits
        assert "tool-b" not in open_circuits


class TestCircuitBreakerThreadSafety:
    """Tests for thread safety."""
    
    def test_concurrent_failures(self):
        """Concurrent failures don't corrupt state."""
        cb = CircuitBreaker(name="test-tool", failure_threshold=100)
        
        def record_failures():
            for _ in range(50):
                cb.record_failure()
        
        threads = [threading.Thread(target=record_failures) for _ in range(4)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        stats = cb.get_stats()
        assert stats["failure_count"] == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
