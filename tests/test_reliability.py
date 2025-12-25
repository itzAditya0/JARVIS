"""
Reliability Tests
------------------
Tests for v0.8.0 failure isolation and degradation.

Tests cover:
- Failure budget enforcement
- Degradation policies
- Dependency-aware aborts
- Exception classification
- Health monitoring integration
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.degradation import (
    FailureBudget, DegradationPolicy, DegradationStrategy,
    DegradationManager, classify_exception
)
from core.errors import JARVISError, ErrorCategory
from tools.registry import PermissionLevel
from infra.health import HealthMonitor, HealthStatus, ComponentHealth


class TestFailureBudget:
    """Tests for failure budget enforcement."""
    
    def test_initial_state(self):
        """Budget starts with zero failures."""
        budget = FailureBudget()
        
        assert not budget.should_abort()
        stats = budget.get_stats()
        assert stats["total_failures"] == 0
    
    def test_abort_on_max_failures(self):
        """Budget triggers abort after max failures."""
        budget = FailureBudget(max_failures_per_turn=3, max_consecutive_failures=10)
        
        budget.record_failure("tool-a")
        budget.record_success()  # Reset consecutive
        budget.record_failure("tool-b")
        budget.record_success()  # Reset consecutive
        assert not budget.should_abort()
        
        budget.record_failure("tool-c")
        assert budget.should_abort()
    
    def test_abort_on_consecutive_failures(self):
        """Budget triggers abort after consecutive failures."""
        budget = FailureBudget(max_consecutive_failures=2)
        
        budget.record_failure("tool-a")
        assert not budget.should_abort()
        
        budget.record_failure("tool-a")
        assert budget.should_abort()
    
    def test_success_resets_consecutive(self):
        """Success resets consecutive failure counter."""
        budget = FailureBudget(max_consecutive_failures=2, max_failures_per_turn=10)
        
        budget.record_failure("tool-a")
        budget.record_success()
        budget.record_failure("tool-b")
        
        assert not budget.should_abort()
    
    def test_skipped_tools_tracked(self):
        """Skipped tools are tracked for dependency checking."""
        budget = FailureBudget()
        
        budget.record_skip("read_config")
        budget.record_skip("get_weather")
        
        assert budget.is_dependency_skipped(["read_config"])
        assert not budget.is_dependency_skipped(["write_file"])
    
    def test_reset_clears_all(self):
        """Reset clears all failure tracking."""
        budget = FailureBudget()
        
        budget.record_failure("tool-a")
        budget.record_skip("tool-b")
        budget.reset()
        
        stats = budget.get_stats()
        assert stats["total_failures"] == 0
        assert len(stats["skipped_tools"]) == 0


class TestDegradationPolicy:
    """Tests for degradation policies."""
    
    def test_skip_allowed_for_read(self):
        """READ tools can be skipped."""
        policy = DegradationPolicy(
            tool_name="get_weather",
            strategy=DegradationStrategy.SKIP,
            is_critical=False
        )
        
        assert policy.allows_skip()
    
    def test_skip_denied_for_critical(self):
        """Critical tools cannot be skipped."""
        policy = DegradationPolicy(
            tool_name="write_file",
            strategy=DegradationStrategy.SKIP,
            is_critical=True
        )
        
        assert not policy.allows_skip()
    
    def test_fail_fast_no_skip(self):
        """FAIL_FAST strategy disallows skip."""
        policy = DegradationPolicy(
            tool_name="execute_command",
            strategy=DegradationStrategy.FAIL_FAST,
            is_critical=False
        )
        
        assert not policy.allows_skip()


class TestDegradationManager:
    """Tests for degradation manager."""
    
    def test_default_policy_read(self):
        """READ tools get RETRY strategy by default."""
        manager = DegradationManager()
        
        policy = manager.get_policy("get_time", PermissionLevel.READ)
        
        assert policy.strategy == DegradationStrategy.RETRY
        assert not policy.is_critical
    
    def test_default_policy_write(self):
        """WRITE tools get FAIL_FAST by default."""
        manager = DegradationManager()
        
        policy = manager.get_policy("save_file", PermissionLevel.WRITE)
        
        assert policy.strategy == DegradationStrategy.FAIL_FAST
        assert policy.is_critical
    
    def test_should_skip_respects_budget(self):
        """should_skip respects failure budget."""
        manager = DegradationManager()
        budget = FailureBudget(max_failures_per_turn=2, max_consecutive_failures=10)
        
        budget.record_failure("tool-a")
        budget.record_success()
        budget.record_failure("tool-b")
        
        # Set policy to allow skip
        manager.set_policy(DegradationPolicy(
            tool_name="read_config",
            strategy=DegradationStrategy.SKIP,
            is_critical=False
        ))
        
        should_skip, reason = manager.should_skip(
            "read_config",
            PermissionLevel.READ,
            budget
        )
        
        assert not should_skip
        assert "exceeded" in reason.lower() or "abort" in reason.lower()
    
    def test_dependency_aware_abort(self):
        """Skipping aborts if dependency was skipped."""
        manager = DegradationManager()
        budget = FailureBudget()
        
        budget.record_skip("read_config")
        
        # Set policy to allow skip
        manager.set_policy(DegradationPolicy(
            tool_name="process_data",
            strategy=DegradationStrategy.SKIP,
            is_critical=False
        ))
        
        should_skip, reason = manager.should_skip(
            "process_data",
            PermissionLevel.READ,
            budget,
            dependencies=["read_config"]
        )
        
        assert not should_skip
        assert "dependency" in reason.lower()


class TestExceptionClassification:
    """Tests for exception → JARVISError classification."""
    
    def test_timeout_classified(self):
        """TimeoutError classified as TIMEOUT_ERROR."""
        error = classify_exception(TimeoutError("timed out"), "my_tool")
        
        assert error.category == ErrorCategory.TIMEOUT_ERROR
        assert error.details["tool"] == "my_tool"
    
    def test_permission_classified(self):
        """PermissionError classified as PERMISSION_ERROR."""
        error = classify_exception(PermissionError("denied"), "my_tool")
        
        assert error.category == ErrorCategory.PERMISSION_ERROR
    
    def test_connection_classified(self):
        """ConnectionError classified as NETWORK_ERROR."""
        error = classify_exception(ConnectionError("refused"), "my_tool")
        
        assert error.category == ErrorCategory.NETWORK_ERROR
    
    def test_value_error_classified(self):
        """ValueError classified as VALIDATION_ERROR."""
        error = classify_exception(ValueError("invalid"), "my_tool")
        
        assert error.category == ErrorCategory.VALIDATION_ERROR
    
    def test_generic_exception_classified(self):
        """Generic exception classified as TOOL_FAILURE."""
        error = classify_exception(RuntimeError("something broke"), "my_tool")
        
        assert error.category == ErrorCategory.TOOL_FAILURE


class TestHealthMonitor:
    """Tests for health monitoring."""
    
    def test_initial_healthy(self):
        """Components start healthy."""
        monitor = HealthMonitor()
        
        health = monitor.get_or_create("test-component")
        
        assert health.status == HealthStatus.HEALTHY
    
    def test_degrades_on_errors(self):
        """Component degrades with high error rate."""
        monitor = HealthMonitor()
        
        # 2 errors out of 10 calls = 20% error rate
        for i in range(10):
            monitor.record_call("test-comp", latency_ms=10.0, is_error=(i < 2))
        
        health = monitor.get_or_create("test-comp")
        assert health.status == HealthStatus.DEGRADED
    
    def test_unhealthy_on_high_errors(self):
        """Component unhealthy with very high error rate."""
        monitor = HealthMonitor()
        
        # 5 errors out of 10 calls = 50% error rate
        for i in range(10):
            monitor.record_call("test-comp", latency_ms=10.0, is_error=(i < 5))
        
        health = monitor.get_or_create("test-comp")
        assert health.status == HealthStatus.UNHEALTHY
    
    def test_get_unhealthy_list(self):
        """Can get list of unhealthy components."""
        monitor = HealthMonitor()
        
        # Make one component unhealthy
        for _ in range(10):
            monitor.record_call("bad-comp", latency_ms=10.0, is_error=True)
        
        # Keep one healthy
        for _ in range(10):
            monitor.record_call("good-comp", latency_ms=10.0, is_error=False)
        
        unhealthy = monitor.get_unhealthy()
        
        assert "bad-comp" in unhealthy
        assert "good-comp" not in unhealthy
    
    def test_overall_status(self):
        """Overall status reflects worst component."""
        monitor = HealthMonitor()
        
        # Add healthy and unhealthy components
        for _ in range(10):
            monitor.record_call("good", latency_ms=10.0, is_error=False)
            monitor.record_call("bad", latency_ms=10.0, is_error=True)
        
        summary = monitor.get_summary()
        
        assert summary["overall_status"] == "UNHEALTHY"


class TestIntegration:
    """Integration tests for reliability components."""
    
    def test_circuit_health_degradation_flow(self):
        """
        Full flow: circuit opens → health shows UNHEALTHY → degradation kicks in.
        """
        from core.circuit_breaker import CircuitBreaker
        
        # Setup
        monitor = HealthMonitor()
        budget = FailureBudget(max_failures_per_turn=5)
        manager = DegradationManager()
        cb = CircuitBreaker(name="flaky_api", failure_threshold=3)
        
        # Simulate failures
        for i in range(3):
            cb.record_failure()
            monitor.record_call("flaky_api", latency_ms=100.0, is_error=True)
            budget.record_failure("flaky_api")
        
        # Verify circuit is open
        assert cb.is_open
        
        # Verify health is unhealthy
        health = monitor.get_or_create("flaky_api")
        assert health.status == HealthStatus.UNHEALTHY
        
        # Verify degradation policy
        policy = manager.get_policy("flaky_api", PermissionLevel.NETWORK)
        assert policy.strategy == DegradationStrategy.RETRY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
