"""
Confirmation Workflow Tests
----------------------------
Tests for v0.6.0 confirmation gates.

Tests cover:
- Confirmation required detection
- Approval flow
- Denial flow
- Timeout behavior
- Callback-based confirmation
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.executor import (
    ToolExecutor, ExecutionStatus, ExecutionContext,
    PendingConfirmation, ExecutionResult
)
from tools.registry import create_default_tools, PermissionLevel
from tools.authority import ToolAuthority


class TestConfirmationRequired:
    """Tests for confirmation requirement detection."""
    
    @pytest.fixture
    def executor(self):
        """Create executor with default tools."""
        registry = create_default_tools()
        return ToolExecutor(registry)
    
    def test_read_tool_no_confirmation(self, executor):
        """READ tools with grants don't require confirmation."""
        result = executor.execute("get_current_time", {})
        
        assert result.success
        assert not result.needs_confirmation
    
    def test_write_tool_requires_confirmation(self, executor):
        """WRITE tools require confirmation by default."""
        # open_application is EXECUTE level
        result = executor.execute("open_application", {"app_name": "Safari"})
        
        # Should require confirmation
        assert result.needs_confirmation or result.status == ExecutionStatus.PERMISSION_DENIED
    
    def test_confirmation_returns_pending(self, executor):
        """Confirmation required returns pending confirmation details."""
        result = executor.execute("open_application", {"app_name": "Safari"})
        
        if result.needs_confirmation:
            assert result.pending_confirmation is not None
            assert result.pending_confirmation.tool_name == "open_application"
            assert result.pending_confirmation.id is not None


class TestConfirmationCallback:
    """Tests for callback-based confirmation."""
    
    @pytest.fixture
    def executor(self):
        """Create executor with default tools."""
        registry = create_default_tools()
        return ToolExecutor(registry)
    
    def test_callback_approval(self, executor):
        """Approved callback executes tool."""
        def approve_callback(pending: PendingConfirmation) -> bool:
            return True
        
        result = executor.execute(
            "open_application",
            {"app_name": "Safari"},
            confirm_callback=approve_callback
        )
        
        # Should execute (or fail for other reasons, but not confirmation)
        assert result.status != ExecutionStatus.CONFIRMATION_REQUIRED
        assert result.status != ExecutionStatus.CONFIRMATION_DENIED
    
    def test_callback_denial(self, executor):
        """Denied callback returns CONFIRMATION_DENIED."""
        def deny_callback(pending: PendingConfirmation) -> bool:
            return False
        
        result = executor.execute(
            "open_application",
            {"app_name": "Safari"},
            confirm_callback=deny_callback
        )
        
        assert result.status == ExecutionStatus.CONFIRMATION_DENIED
        assert "denied" in result.error.lower()


class TestPendingConfirmation:
    """Tests for pending confirmation workflow."""
    
    @pytest.fixture
    def executor(self):
        """Create executor with default tools."""
        registry = create_default_tools()
        return ToolExecutor(registry)
    
    def test_pending_confirmation_id(self, executor):
        """Pending confirmation has unique ID."""
        result = executor.execute("open_application", {"app_name": "Safari"})
        
        if result.needs_confirmation:
            assert len(result.pending_confirmation.id) > 0
    
    def test_confirm_pending_approval(self, executor):
        """confirm_pending with approval executes tool."""
        result = executor.execute("open_application", {"app_name": "Safari"})
        
        if result.needs_confirmation:
            confirmation_id = result.pending_confirmation.id
            
            result2 = executor.confirm_pending(confirmation_id, approved=True)
            
            # Should execute (or fail for app reasons, not confirmation)
            assert result2.status != ExecutionStatus.CONFIRMATION_REQUIRED
    
    def test_confirm_pending_denial(self, executor):
        """confirm_pending with denial returns CONFIRMATION_DENIED."""
        result = executor.execute("open_application", {"app_name": "Safari"})
        
        if result.needs_confirmation:
            confirmation_id = result.pending_confirmation.id
            
            result2 = executor.confirm_pending(confirmation_id, approved=False)
            
            assert result2.status == ExecutionStatus.CONFIRMATION_DENIED
    
    def test_confirm_pending_unknown_id(self, executor):
        """confirm_pending with unknown ID returns error."""
        result = executor.confirm_pending("unknown-id", approved=True)
        
        assert result.status == ExecutionStatus.EXECUTION_ERROR
        assert "unknown" in result.error.lower()
    
    def test_confirmation_expiry(self, executor):
        """Expired confirmation returns CONFIRMATION_TIMEOUT."""
        result = executor.execute("open_application", {"app_name": "Safari"})
        
        if result.needs_confirmation:
            confirmation_id = result.pending_confirmation.id
            
            # Manually expire the pending confirmation
            pending = executor._pending_confirmations.get(confirmation_id)
            if pending:
                pending.expires_in_seconds = 0
                pending.requested_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            
            result2 = executor.confirm_pending(confirmation_id, approved=True)
            
            assert result2.status == ExecutionStatus.CONFIRMATION_TIMEOUT


class TestTurnIdPropagation:
    """Tests for turn_id propagation through confirmation workflow."""
    
    @pytest.fixture
    def executor(self):
        """Create executor with default tools."""
        registry = create_default_tools()
        return ToolExecutor(registry)
    
    def test_turn_id_in_result(self, executor):
        """turn_id is preserved in execution result."""
        result = executor.execute(
            "get_current_time",
            {},
            turn_id="test-turn-456"
        )
        
        assert result.turn_id == "test-turn-456"
    
    def test_turn_id_in_pending_confirmation(self, executor):
        """turn_id is preserved in pending confirmation."""
        result = executor.execute(
            "open_application",
            {"app_name": "Safari"},
            turn_id="test-turn-789"
        )
        
        if result.needs_confirmation:
            assert result.pending_confirmation.turn_id == "test-turn-789"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
