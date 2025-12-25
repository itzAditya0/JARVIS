"""
Memory Governance Tests
------------------------
Tests for v0.6.0 memory policy enforcement.

Tests cover:
- Redaction of sensitive patterns
- Retention policy enforcement
- User deletion commands
- Audit logging
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.governance import (
    MemoryGovernor, MemoryPolicy, RedactionResult, DeletionResult
)


class TestRedaction:
    """Tests for sensitive data redaction."""
    
    @pytest.fixture
    def governor(self):
        """Create governor with default policy."""
        policy = MemoryPolicy(
            sensitive_patterns=[
                r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',  # Credit card
                r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b',              # SSN
            ]
        )
        return MemoryGovernor(policy=policy)
    
    def test_credit_card_redacted(self, governor):
        """Credit card numbers are redacted."""
        content = "My card is 1234-5678-9012-3456"
        redacted, result = governor.redact(content)
        
        assert "[REDACTED]" in redacted
        assert "1234-5678-9012-3456" not in redacted
        assert result.was_redacted
        assert result.redaction_count == 1
    
    def test_ssn_redacted(self, governor):
        """SSN numbers are redacted."""
        content = "SSN: 123-45-6789"
        redacted, result = governor.redact(content)
        
        assert "[REDACTED]" in redacted
        assert "123-45-6789" not in redacted
    
    def test_no_sensitive_data(self, governor):
        """Content without sensitive data is unchanged."""
        content = "Just a normal message"
        redacted, result = governor.redact(content)
        
        assert redacted == content
        assert not result.was_redacted
        assert result.redaction_count == 0
    
    def test_multiple_patterns(self, governor):
        """Multiple sensitive items are redacted."""
        content = "Card: 1234-5678-9012-3456, SSN: 123-45-6789"
        redacted, result = governor.redact(content)
        
        assert result.redaction_count == 2
        assert "1234" not in redacted
        assert "6789" not in redacted
    
    def test_redaction_disabled(self):
        """Redaction can be disabled."""
        policy = MemoryPolicy(redact_on_store=False)
        governor = MemoryGovernor(policy=policy)
        
        content = "Card: 1234-5678-9012-3456"
        redacted, result = governor.redact(content)
        
        assert redacted == content
        assert not result.was_redacted


class TestRetentionPolicy:
    """Tests for retention policy enforcement."""
    
    @pytest.fixture
    def governor(self):
        """Create governor with strict limits for testing."""
        policy = MemoryPolicy(
            max_turns=3,
            max_age_days=1
        )
        return MemoryGovernor(policy=policy)
    
    def create_mock_turn(self, content: str, age_days: int = 0):
        """Create a mock turn object."""
        from dataclasses import dataclass
        
        @dataclass
        class MockTurn:
            content: str
            timestamp: datetime
        
        timestamp = datetime.now(timezone.utc) - timedelta(days=age_days)
        return MockTurn(content=content, timestamp=timestamp)
    
    def test_old_turns_removed(self, governor):
        """Turns older than max_age_days are removed."""
        old_turn = self.create_mock_turn("old", age_days=5)
        new_turn = self.create_mock_turn("new", age_days=0)
        
        retained, result = governor.enforce_retention([old_turn, new_turn])
        
        assert len(retained) == 1
        assert retained[0].content == "new"
        assert result.items_deleted == 1
    
    def test_excess_turns_removed(self, governor):
        """Excess turns beyond max_turns are removed (oldest first)."""
        turns = [self.create_mock_turn(f"turn{i}", age_days=0) for i in range(5)]
        
        retained, result = governor.enforce_retention(turns)
        
        assert len(retained) == 3  # max_turns
        assert result.items_deleted == 2
    
    def test_recent_turns_kept(self, governor):
        """Recent turns within limits are kept."""
        turns = [self.create_mock_turn(f"turn{i}", age_days=0) for i in range(2)]
        
        retained, result = governor.enforce_retention(turns)
        
        assert len(retained) == 2
        assert result.items_deleted == 0
    
    def test_empty_input(self, governor):
        """Empty input returns empty output."""
        retained, result = governor.enforce_retention([])
        
        assert len(retained) == 0
        assert result.items_deleted == 0


class TestDeletionCommands:
    """Tests for user-triggered deletion."""
    
    @pytest.fixture
    def governor(self):
        """Create governor without DB."""
        return MemoryGovernor()
    
    def test_forget_all_logs(self, governor):
        """forget_all creates a deletion log entry."""
        result = governor.forget_all(turn_id="test-turn")
        
        assert result.reason == "User requested: forget everything"
        assert result.turn_id == "test-turn"
        
        log = governor.get_deletion_log()
        assert len(log) == 1
    
    def test_forget_conversation_logs(self, governor):
        """forget_conversation creates a deletion log entry."""
        result = governor.forget_conversation("conv-123", turn_id="test-turn")
        
        assert "conv-123" in result.reason
        assert result.turn_id == "test-turn"
    
    def test_deletion_log_preserved(self, governor):
        """Deletion log preserves history."""
        governor.forget_all()
        governor.forget_conversation("conv-1")
        governor.forget_conversation("conv-2")
        
        log = governor.get_deletion_log()
        assert len(log) == 3


class TestMemorySummary:
    """Tests for memory summary generation."""
    
    @pytest.fixture
    def governor(self):
        """Create governor without DB."""
        return MemoryGovernor()
    
    def test_summary_includes_policy(self, governor):
        """Summary includes policy information."""
        summary = governor.get_memory_summary()
        
        assert "policy" in summary
        assert "max_turns" in summary["policy"]
        assert "max_age_days" in summary["policy"]
    
    def test_summary_includes_deletion_count(self, governor):
        """Summary includes deletion count."""
        governor.forget_all()
        
        summary = governor.get_memory_summary()
        assert summary["deletions_performed"] == 1


class TestTurnIdPropagation:
    """Tests for turn_id in governance operations."""
    
    @pytest.fixture
    def governor(self):
        return MemoryGovernor()
    
    def test_redaction_accepts_turn_id(self, governor):
        """redact() accepts turn_id parameter."""
        # Should not raise
        content, result = governor.redact("test", turn_id="turn-123")
        assert content == "test"
    
    def test_retention_accepts_turn_id(self, governor):
        """enforce_retention() accepts turn_id parameter."""
        retained, result = governor.enforce_retention([], turn_id="turn-456")
        assert result.turn_id is None or result.turn_id == "turn-456"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
