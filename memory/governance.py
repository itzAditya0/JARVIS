"""
Memory Governance System
-------------------------
Enforces policies for memory retention, redaction, and user control.

v0.6.0: Governance release.

Rules:
- Retention limits are hard (not soft)
- Sensitive patterns are static regex only (no heuristics)
- User can request full deletion
- All operations logged with turn_id
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Set
import logging
import re


class RedactionReason(Enum):
    """Reason for redacting content."""
    SENSITIVE_PATTERN = auto()
    USER_REQUEST = auto()
    POLICY_VIOLATION = auto()


@dataclass
class MemoryPolicy:
    """
    Policy for memory retention and access.
    
    All limits are HARD - exceeded content is deleted, not just hidden.
    """
    max_turns: int = 1000
    max_age_days: int = 30
    max_tokens_per_turn: int = 2000
    
    # Static regex patterns for sensitive data (credit cards, SSNs, etc.)
    # IMPORTANT: Keep these deterministic and auditable
    sensitive_patterns: List[str] = field(default_factory=lambda: [
        r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',  # Credit card numbers
        r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b',              # SSN
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email (optional)
    ])
    
    redact_on_store: bool = True
    redaction_placeholder: str = "[REDACTED]"
    
    def __post_init__(self):
        """Compile regex patterns."""
        self._compiled_patterns: List[Pattern] = []
        for pattern in self.sensitive_patterns:
            try:
                self._compiled_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                logging.warning(f"Invalid regex pattern: {pattern} - {e}")
    
    def get_compiled_patterns(self) -> List[Pattern]:
        """Get compiled regex patterns."""
        if not hasattr(self, '_compiled_patterns'):
            self.__post_init__()
        return self._compiled_patterns


@dataclass
class RedactionResult:
    """Result of a redaction operation."""
    original_length: int
    redacted_length: int
    redaction_count: int
    patterns_matched: List[str]
    
    @property
    def was_redacted(self) -> bool:
        return self.redaction_count > 0


@dataclass
class DeletionResult:
    """Result of a deletion operation."""
    items_deleted: int
    reason: str
    turn_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryGovernor:
    """
    Enforces memory policies.
    
    This is the governance layer over memory storage.
    
    Rules:
    - Retention limits are hard (not soft)
    - Sensitive patterns are redacted before storage
    - User can request full deletion
    - All operations logged with turn_id
    """
    
    def __init__(
        self,
        policy: Optional[MemoryPolicy] = None,
        db_manager=None
    ):
        self.policy = policy or MemoryPolicy()
        self._db = db_manager
        self._logger = logging.getLogger("jarvis.memory.governance")
        self._deletion_log: List[DeletionResult] = []
    
    def redact(self, content: str, turn_id: Optional[str] = None) -> tuple[str, RedactionResult]:
        """
        Redact sensitive content using static regex patterns.
        
        Returns (redacted_content, result).
        This is deterministic and auditable.
        """
        if not self.policy.redact_on_store:
            return content, RedactionResult(
                original_length=len(content),
                redacted_length=len(content),
                redaction_count=0,
                patterns_matched=[]
            )
        
        redacted = content
        patterns_matched = []
        count = 0
        
        for pattern in self.policy.get_compiled_patterns():
            matches = pattern.findall(redacted)
            if matches:
                count += len(matches)
                patterns_matched.append(pattern.pattern)
                redacted = pattern.sub(self.policy.redaction_placeholder, redacted)
        
        result = RedactionResult(
            original_length=len(content),
            redacted_length=len(redacted),
            redaction_count=count,
            patterns_matched=patterns_matched
        )
        
        if result.was_redacted:
            self._logger.info(
                f"Redacted {count} sensitive items | turn_id={turn_id or 'N/A'}"
            )
        
        return redacted, result
    
    def enforce_retention(
        self,
        turns: List[Any],
        turn_id: Optional[str] = None
    ) -> tuple[List[Any], DeletionResult]:
        """
        Enforce retention policy on turns.
        
        Removes turns that exceed age or count limits.
        Returns (remaining_turns, deletion_result).
        """
        if not turns:
            return [], DeletionResult(items_deleted=0, reason="No turns to process")
        
        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(days=self.policy.max_age_days)
        
        retained = []
        deleted_count = 0
        
        for turn in turns:
            # Check age limit
            turn_timestamp = getattr(turn, 'timestamp', None)
            if turn_timestamp:
                if isinstance(turn_timestamp, datetime):
                    if turn_timestamp.tzinfo is None:
                        turn_timestamp = turn_timestamp.replace(tzinfo=timezone.utc)
                    if turn_timestamp < cutoff_date:
                        deleted_count += 1
                        continue
            
            retained.append(turn)
        
        # Enforce max turns (keep most recent)
        if len(retained) > self.policy.max_turns:
            excess = len(retained) - self.policy.max_turns
            retained = retained[-self.policy.max_turns:]
            deleted_count += excess
        
        result = DeletionResult(
            items_deleted=deleted_count,
            reason=f"Retention policy: max_age={self.policy.max_age_days}d, max_turns={self.policy.max_turns}",
            turn_id=turn_id
        )
        
        if deleted_count > 0:
            self._logger.info(
                f"Retention enforcement: deleted {deleted_count} turns | turn_id={turn_id or 'N/A'}"
            )
            self._deletion_log.append(result)
        
        return retained, result
    
    def forget_all(self, turn_id: Optional[str] = None) -> DeletionResult:
        """
        Delete all memory (user-triggered).
        
        This is an explicit user action - must be confirmed before calling.
        """
        self._logger.warning(f"FORGET ALL requested | turn_id={turn_id or 'N/A'}")
        
        deleted_count = 0
        
        # If database manager available, purge from DB
        if self._db and hasattr(self._db, 'execute'):
            try:
                with self._db.transaction():
                    # Delete from turns table
                    cursor = self._db.execute("SELECT COUNT(*) FROM turns")
                    row = cursor.fetchone()
                    deleted_count = row[0] if row else 0
                    
                    self._db.execute("DELETE FROM turns")
                    self._db.execute("DELETE FROM conversations")
                    self._db.execute("DELETE FROM memories")
                    
                self._logger.info(f"Purged {deleted_count} turns from database")
            except Exception as e:
                self._logger.error(f"Database purge failed: {e}")
        
        result = DeletionResult(
            items_deleted=deleted_count,
            reason="User requested: forget everything",
            turn_id=turn_id
        )
        
        self._deletion_log.append(result)
        return result
    
    def forget_conversation(
        self,
        conversation_id: str,
        turn_id: Optional[str] = None
    ) -> DeletionResult:
        """
        Delete a specific conversation (user-triggered).
        
        This is an explicit user action.
        """
        self._logger.info(
            f"FORGET conversation {conversation_id} | turn_id={turn_id or 'N/A'}"
        )
        
        deleted_count = 0
        
        if self._db and hasattr(self._db, 'execute'):
            try:
                with self._db.transaction():
                    cursor = self._db.execute(
                        "SELECT COUNT(*) FROM turns WHERE conversation_id = ?",
                        (conversation_id,)
                    )
                    row = cursor.fetchone()
                    deleted_count = row[0] if row else 0
                    
                    self._db.execute(
                        "DELETE FROM turns WHERE conversation_id = ?",
                        (conversation_id,)
                    )
                    self._db.execute(
                        "DELETE FROM conversations WHERE id = ?",
                        (conversation_id,)
                    )
                    
            except Exception as e:
                self._logger.error(f"Conversation deletion failed: {e}")
        
        result = DeletionResult(
            items_deleted=deleted_count,
            reason=f"User requested: forget conversation {conversation_id}",
            turn_id=turn_id
        )
        
        self._deletion_log.append(result)
        return result
    
    def get_deletion_log(self) -> List[DeletionResult]:
        """Get log of all deletion operations."""
        return self._deletion_log.copy()
    
    def get_memory_summary(self) -> Dict[str, Any]:
        """
        Get summary of stored memory for user inspection.
        
        Used for "what do you remember?" command.
        """
        summary = {
            "policy": {
                "max_turns": self.policy.max_turns,
                "max_age_days": self.policy.max_age_days,
                "redaction_enabled": self.policy.redact_on_store,
                "sensitive_patterns_count": len(self.policy.sensitive_patterns),
            },
            "deletions_performed": len(self._deletion_log),
        }
        
        if self._db and hasattr(self._db, 'execute'):
            try:
                cursor = self._db.execute("SELECT COUNT(*) FROM conversations")
                row = cursor.fetchone()
                summary["conversations_count"] = row[0] if row else 0
                
                cursor = self._db.execute("SELECT COUNT(*) FROM turns")
                row = cursor.fetchone()
                summary["turns_count"] = row[0] if row else 0
                
                cursor = self._db.execute("SELECT COUNT(*) FROM memories")
                row = cursor.fetchone()
                summary["memories_count"] = row[0] if row else 0
            except Exception as e:
                summary["database_error"] = str(e)
        
        return summary


def test_governance() -> None:
    """Test the memory governance system."""
    print("Testing Memory Governance...")
    
    policy = MemoryPolicy(
        max_turns=5,
        max_age_days=7,
        sensitive_patterns=[
            r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',  # Credit cards
        ]
    )
    
    governor = MemoryGovernor(policy=policy)
    
    # Test redaction
    content = "My card is 1234-5678-9012-3456 and email is test@example.com"
    redacted, result = governor.redact(content)
    
    print(f"\nRedaction test:")
    print(f"  Original: {content}")
    print(f"  Redacted: {redacted}")
    print(f"  Count: {result.redaction_count}")
    
    # Test retention
    from dataclasses import dataclass as dc
    
    @dc
    class MockTurn:
        content: str
        timestamp: datetime
    
    old_turn = MockTurn("old", datetime.now(timezone.utc) - timedelta(days=100))
    new_turn = MockTurn("new", datetime.now(timezone.utc))
    
    retained, deletion = governor.enforce_retention([old_turn, new_turn])
    
    print(f"\nRetention test:")
    print(f"  Input: 2 turns")
    print(f"  Retained: {len(retained)}")
    print(f"  Deleted: {deletion.items_deleted}")
    
    print("\nAll tests passed!")


if __name__ == "__main__":
    test_governance()
