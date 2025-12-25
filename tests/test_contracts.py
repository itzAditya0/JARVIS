"""
Contract Tests
---------------
API surface tests for v0.9.0 contract freeze.

These tests verify:
- Public symbols exist
- Required types are exported
- Breaking changes cause test failure
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCoreErrorsAPI:
    """Verify core.errors exports."""
    
    def test_exports_exist(self):
        from core.errors import (
            JARVISError,
            ErrorCategory,
            RetryPolicy,
            ErrorHandler,
            create_tool_error,
            create_validation_error,
            create_llm_error,
            create_permission_error,
        )
        
        assert JARVISError is not None
        assert ErrorCategory is not None
        assert RetryPolicy is not None
    
    def test_error_category_values(self):
        from core.errors import ErrorCategory
        
        # These values must remain stable
        assert hasattr(ErrorCategory, 'TOOL_FAILURE')
        assert hasattr(ErrorCategory, 'VALIDATION_ERROR')
        assert hasattr(ErrorCategory, 'LLM_FAILURE')
        assert hasattr(ErrorCategory, 'LLM_HALLUCINATION')
        assert hasattr(ErrorCategory, 'PERMISSION_ERROR')


class TestCircuitBreakerAPI:
    """Verify core.circuit_breaker exports."""
    
    def test_exports_exist(self):
        from core.circuit_breaker import (
            CircuitBreaker,
            CircuitState,
            CircuitOpenError,
            CircuitBreakerRegistry,
            get_circuit_breaker,
            get_circuit_registry,
        )
        
        assert CircuitBreaker is not None
        assert CircuitState is not None
    
    def test_circuit_state_values(self):
        from core.circuit_breaker import CircuitState
        
        assert hasattr(CircuitState, 'CLOSED')
        assert hasattr(CircuitState, 'OPEN')
        assert hasattr(CircuitState, 'HALF_OPEN')


class TestDegradationAPI:
    """Verify core.degradation exports."""
    
    def test_exports_exist(self):
        from core.degradation import (
            DegradationStrategy,
            DegradationPolicy,
            FailureBudget,
            DegradationManager,
            classify_exception,
            get_degradation_manager,
        )
        
        assert FailureBudget is not None
        assert DegradationManager is not None
    
    def test_strategy_values(self):
        from core.degradation import DegradationStrategy
        
        assert hasattr(DegradationStrategy, 'FAIL_FAST')
        assert hasattr(DegradationStrategy, 'RETRY')
        assert hasattr(DegradationStrategy, 'SKIP')


class TestToolAuthorityAPI:
    """Verify tools.authority exports."""
    
    def test_exports_exist(self):
        from tools.authority import (
            ToolAuthority,
            PermissionGrant,
            AuthorityDecision,
            GrantStatus,
        )
        
        assert ToolAuthority is not None
        assert PermissionGrant is not None
    
    def test_grant_status_values(self):
        from tools.authority import GrantStatus
        
        assert hasattr(GrantStatus, 'GRANTED')
        assert hasattr(GrantStatus, 'DENIED_NO_GRANT')


class TestToolExecutorAPI:
    """Verify tools.executor exports."""
    
    def test_exports_exist(self):
        from tools.executor import (
            ToolExecutor,
            ExecutionResult,
            ExecutionStatus,
            ExecutionContext,
            PendingConfirmation,
        )
        
        assert ToolExecutor is not None
        assert ExecutionResult is not None
    
    def test_execution_status_values(self):
        from tools.executor import ExecutionStatus
        
        assert hasattr(ExecutionStatus, 'SUCCESS')
        assert hasattr(ExecutionStatus, 'PERMISSION_DENIED')
        assert hasattr(ExecutionStatus, 'CONFIRMATION_REQUIRED')


class TestAuditAPI:
    """Verify infra.audit exports."""
    
    def test_exports_exist(self):
        from infra.audit import (
            AuditLog,
            AuditEntry,
            EventType,
            Actor,
            VerifyResult,
            get_audit_log,
            audit_event,
        )
        
        assert AuditLog is not None
        assert AuditEntry is not None
    
    def test_event_type_values(self):
        from infra.audit import EventType
        
        assert hasattr(EventType, 'TURN_START')
        assert hasattr(EventType, 'TURN_END')
        assert hasattr(EventType, 'TOOL_EXECUTE')
        assert hasattr(EventType, 'AUTHORITY_CHECK')


class TestHealthAPI:
    """Verify infra.health exports."""
    
    def test_exports_exist(self):
        from infra.health import (
            HealthMonitor,
            ComponentHealth,
            HealthStatus,
            get_health_monitor,
        )
        
        assert HealthMonitor is not None
        assert HealthStatus is not None
    
    def test_health_status_values(self):
        from infra.health import HealthStatus
        
        assert hasattr(HealthStatus, 'HEALTHY')
        assert hasattr(HealthStatus, 'DEGRADED')
        assert hasattr(HealthStatus, 'UNHEALTHY')


class TestMemoryGovernanceAPI:
    """Verify memory.governance exports."""
    
    def test_exports_exist(self):
        from memory.governance import (
            MemoryGovernor,
            MemoryPolicy,
        )
        
        assert MemoryGovernor is not None
        assert MemoryPolicy is not None


class TestToolRegistryAPI:
    """Verify tools.registry exports."""
    
    def test_exports_exist(self):
        from tools.registry import (
            Tool,
            ToolSchema,
            ToolParameter,
            ToolRegistry,
            PermissionLevel,
        )
        
        assert Tool is not None
        assert ToolRegistry is not None
    
    def test_permission_level_values(self):
        from tools.registry import PermissionLevel
        
        assert hasattr(PermissionLevel, 'READ')
        assert hasattr(PermissionLevel, 'WRITE')
        assert hasattr(PermissionLevel, 'EXECUTE')
        assert hasattr(PermissionLevel, 'NETWORK')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
