"""
Audit Log Tests
----------------
Tests for v0.7.0 accountability guarantees.

Tests cover:
- Entry append
- Chain integrity
- Tamper detection (including attack simulation)
- Turn trail reconstruction
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import sqlite3
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.audit import (
    AuditLog, AuditEntry, EventType, Actor, VerifyResult,
    get_audit_log, audit_event
)


class TestAuditEntryCreation:
    """Tests for AuditEntry basics."""
    
    def test_entry_defaults(self):
        """Entry has sensible defaults."""
        entry = AuditEntry(turn_id="test-123", action="test")
        
        assert entry.turn_id == "test-123"
        assert entry.timestamp is not None
        assert entry.event_type == EventType.TURN_START
    
    def test_entry_to_dict(self):
        """Entry serializes correctly."""
        entry = AuditEntry(
            turn_id="test-456",
            event_type=EventType.TOOL_EXECUTE,
            actor=Actor.EXECUTOR,
            action="execute",
            target="get_current_time",
            details={"args": {"format": "iso"}},
        )
        
        data = entry.to_dict()
        assert data["turn_id"] == "test-456"
        assert data["event_type"] == "TOOL_EXECUTE"
        assert data["actor"] == "executor"


class TestAuditLogAppend:
    """Tests for audit log append operations."""
    
    @pytest.fixture
    def audit_log(self, tmp_path):
        """Create a temporary audit log."""
        db_path = str(tmp_path / "test_audit.db")
        return AuditLog(db_path=db_path, key=b"test-key-12345")
    
    def test_log_entry(self, audit_log):
        """Can log an entry."""
        entry_hash = audit_log.log(
            event_type=EventType.TURN_START,
            actor=Actor.USER,
            action="input",
            turn_id="turn-001",
        )
        
        assert entry_hash is not None
        assert len(entry_hash) == 64  # SHA256 hex
    
    def test_log_with_details(self, audit_log):
        """Can log entry with details dictionary."""
        entry_hash = audit_log.log(
            event_type=EventType.TOOL_EXECUTE,
            actor=Actor.EXECUTOR,
            action="execute",
            turn_id="turn-002",
            target="get_current_time",
            details={"args": {}, "result": "success"},
        )
        
        assert entry_hash is not None
    
    def test_multiple_entries(self, audit_log):
        """Can log multiple entries."""
        for i in range(5):
            audit_log.log(
                event_type=EventType.TURN_START,
                actor=Actor.USER,
                action="input",
                turn_id=f"turn-{i:03d}",
            )
        
        stats = audit_log.get_stats()
        assert stats["total_entries"] == 5


class TestChainIntegrity:
    """Tests for HMAC chain integrity."""
    
    @pytest.fixture
    def audit_log(self, tmp_path):
        """Create a temporary audit log."""
        db_path = str(tmp_path / "test_chain.db")
        return AuditLog(db_path=db_path, key=b"test-key-chain")
    
    def test_first_entry_uses_genesis(self, audit_log):
        """First entry uses genesis hash as prev_hash."""
        audit_log.log(
            event_type=EventType.TURN_START,
            actor=Actor.USER,
            action="input",
            turn_id="first-turn",
        )
        
        entries = audit_log.get_entries()
        assert len(entries) == 1
        assert entries[0].prev_hash == AuditLog.GENESIS_HASH
    
    def test_chain_links_consecutive(self, audit_log):
        """Each entry's prev_hash matches previous entry's hash."""
        for i in range(3):
            audit_log.log(
                event_type=EventType.TURN_START,
                actor=Actor.USER,
                action="input",
                turn_id=f"turn-{i}",
            )
        
        entries = audit_log.get_entries()
        
        # Entry 1 -> genesis
        assert entries[0].prev_hash == AuditLog.GENESIS_HASH
        
        # Entry 2 -> entry 1
        assert entries[1].prev_hash == entries[0].entry_hash
        
        # Entry 3 -> entry 2
        assert entries[2].prev_hash == entries[1].entry_hash
    
    def test_verify_chain_valid(self, audit_log):
        """verify_chain returns valid for untampered log."""
        for i in range(5):
            audit_log.log(
                event_type=EventType.TURN_START,
                actor=Actor.USER,
                action="input",
                turn_id=f"turn-{i}",
            )
        
        result = audit_log.verify_chain()
        
        assert result.valid
        assert result.entries_checked == 5
        assert result.broken_at is None
    
    def test_verify_empty_chain(self, audit_log):
        """verify_chain handles empty log."""
        result = audit_log.verify_chain()
        
        assert result.valid
        assert result.entries_checked == 0


class TestTamperDetection:
    """Tests for tamper detection - the core accountability guarantee."""
    
    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "test_tamper.db")
    
    @pytest.fixture
    def audit_log(self, db_path):
        return AuditLog(db_path=db_path, key=b"test-key-tamper")
    
    def test_content_modification_detected(self, audit_log, db_path):
        """Modifying entry content breaks chain."""
        # Log 3 entries
        for i in range(3):
            audit_log.log(
                event_type=EventType.TURN_START,
                actor=Actor.USER,
                action="input",
                turn_id=f"turn-{i}",
            )
        
        # Verify valid first
        result = audit_log.verify_chain()
        assert result.valid
        
        # Tamper: modify middle entry's action
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE audit_log SET action = 'TAMPERED' WHERE id = 2")
        conn.commit()
        conn.close()
        
        # Verify should fail
        result = audit_log.verify_chain()
        assert not result.valid
        assert result.broken_at == 2
    
    def test_middle_entry_deletion_detected(self, audit_log, db_path):
        """
        Attack simulation: Delete middle entry, recompute hashes.
        
        This proves ordering integrity, not just content integrity.
        """
        # Log 5 entries
        for i in range(5):
            audit_log.log(
                event_type=EventType.TURN_START,
                actor=Actor.USER,
                action=f"action-{i}",
                turn_id=f"turn-{i}",
            )
        
        # Verify valid first
        result = audit_log.verify_chain()
        assert result.valid
        assert result.entries_checked == 5
        
        # Get entries 3, 4, 5 before deletion
        entries_before = audit_log.get_entries()
        entry_2_hash = entries_before[1].entry_hash  # Entry ID 2's hash
        
        # Attack: Delete entry #3 (middle)
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM audit_log WHERE id = 3")
        
        # Attempt to "fix" chain by updating entry #4's prev_hash
        # (simulating an attacker trying to hide the deletion)
        conn.execute(
            "UPDATE audit_log SET prev_hash = ? WHERE id = 4",
            (entry_2_hash,)  # Point to entry 2 instead of deleted 3
        )
        conn.commit()
        conn.close()
        
        # Verify must fail - the hash won't match even with "fixed" prev_hash
        result = audit_log.verify_chain()
        assert not result.valid
        # Should break at entry 4 because its entry_hash was computed with old prev_hash
        assert result.broken_at == 4
    
    def test_hash_recomputation_attack_fails(self, audit_log, db_path):
        """
        Attack: Modify entry and recompute its hash.
        
        This should fail because attacker doesn't have the HMAC key.
        """
        # Log entries
        for i in range(3):
            audit_log.log(
                event_type=EventType.TURN_START,
                actor=Actor.USER,
                action=f"action-{i}",
                turn_id=f"turn-{i}",
            )
        
        # Attacker modifies and tries to recompute hash (without correct key)
        import hashlib
        import hmac
        
        fake_key = b"wrong-key"
        fake_payload = b"tampered content"
        fake_hash = hmac.new(fake_key, fake_payload, hashlib.sha256).hexdigest()
        
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE audit_log SET action = 'TAMPERED', entry_hash = ? WHERE id = 2",
            (fake_hash,)
        )
        conn.commit()
        conn.close()
        
        # Verify fails because hash doesn't match
        result = audit_log.verify_chain()
        assert not result.valid
        assert result.broken_at == 2


class TestTurnTrail:
    """Tests for turn trail reconstruction."""
    
    @pytest.fixture
    def audit_log(self, tmp_path):
        db_path = str(tmp_path / "test_trail.db")
        return AuditLog(db_path=db_path, key=b"test-key-trail")
    
    def test_get_turn_trail(self, audit_log):
        """Can get all entries for a specific turn."""
        # Log interleaved turns
        audit_log.log(EventType.TURN_START, Actor.USER, "input", "turn-A")
        audit_log.log(EventType.TURN_START, Actor.USER, "input", "turn-B")
        audit_log.log(EventType.TOOL_EXECUTE, Actor.EXECUTOR, "execute", "turn-A")
        audit_log.log(EventType.TOOL_EXECUTE, Actor.EXECUTOR, "execute", "turn-B")
        audit_log.log(EventType.TURN_END, Actor.SYSTEM, "complete", "turn-A")
        audit_log.log(EventType.TURN_END, Actor.SYSTEM, "complete", "turn-B")
        
        # Get trail for turn-A
        trail = audit_log.get_turn_trail("turn-A")
        
        assert len(trail) == 3
        assert all(e.turn_id == "turn-A" for e in trail)
        assert trail[0].event_type == EventType.TURN_START
        assert trail[1].event_type == EventType.TOOL_EXECUTE
        assert trail[2].event_type == EventType.TURN_END


class TestExport:
    """Tests for audit export."""
    
    @pytest.fixture
    def audit_log(self, tmp_path):
        db_path = str(tmp_path / "test_export.db")
        return AuditLog(db_path=db_path, key=b"test-key-export")
    
    def test_export_for_review(self, audit_log):
        """Can export entries as JSON bundle."""
        import json
        
        for i in range(3):
            audit_log.log(
                EventType.TURN_START,
                Actor.USER,
                "input",
                f"turn-{i}",
            )
        
        export = audit_log.export_for_review()
        bundle = json.loads(export)
        
        assert bundle["version"] == "0.7.0"
        assert bundle["entry_count"] == 3
        assert len(bundle["entries"]) == 3
        assert bundle["final_hash"] is not None
        assert bundle["key_id"] is not None  # Key fingerprint only


class TestKeyManagement:
    """Tests for HMAC key handling."""
    
    def test_different_keys_different_hashes(self, tmp_path):
        """Different keys produce different hashes."""
        db_path = str(tmp_path / "test_keys.db")
        
        # Log with key A
        log_a = AuditLog(db_path=db_path, key=b"key-A")
        hash_a = log_a.log(EventType.TURN_START, Actor.USER, "input", "turn-1")
        
        # Create new log with key B (same DB)
        db_path_b = str(tmp_path / "test_keys_b.db")
        log_b = AuditLog(db_path=db_path_b, key=b"key-B")
        hash_b = log_b.log(EventType.TURN_START, Actor.USER, "input", "turn-1")
        
        # Hashes should differ (same content, different keys)
        assert hash_a != hash_b
    
    def test_env_key_loading(self, tmp_path, monkeypatch):
        """Key loaded from environment variable."""
        db_path = str(tmp_path / "test_env.db")
        
        monkeypatch.setenv("JARVIS_AUDIT_KEY", "my-secret-key")
        
        log = AuditLog(db_path=db_path)
        
        # Should use the env key
        assert log._key == b"my-secret-key"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
