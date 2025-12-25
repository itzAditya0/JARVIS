"""
Database Persistence Tests
--------------------------
Tests for the JARVIS database layer.

Test Cases:
1. Schema creation and versioning
2. CRUD operations for all entities
3. Transaction rollback on failure
4. Integrity checks
5. Retention policy enforcement
6. Migration and downgrade prevention
"""

import pytest
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.database import (
    DatabaseManager,
    Conversation,
    Turn,
    Memory,
    ScheduledTask,
    DatabaseError,
    SchemaMismatchError,
    SCHEMA_VERSION,
    MAX_TURNS_PER_CONVERSATION,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    db = DatabaseManager(db_path)
    db.initialize()
    
    yield db
    
    db.close()
    Path(db_path).unlink(missing_ok=True)


class TestSchemaManagement:
    """Test schema creation and versioning."""
    
    def test_fresh_database_creation(self, temp_db):
        """Fresh database should be created with correct schema version."""
        cursor = temp_db._conn.execute(
            "SELECT version FROM schema_version ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        
        assert row is not None
        assert row["version"] == SCHEMA_VERSION
    
    def test_tables_exist(self, temp_db):
        """All expected tables should exist."""
        cursor = temp_db._conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            ORDER BY name
        """)
        tables = {row["name"] for row in cursor.fetchall()}
        
        expected = {"schema_version", "conversations", "turns", "memories", "tasks"}
        assert expected.issubset(tables)
    
    def test_integrity_check_passes(self, temp_db):
        """Database should pass integrity check."""
        cursor = temp_db._conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()[0]
        
        assert result == "ok"
    
    def test_downgrade_prevention(self, temp_db):
        """Attempting to open with older code should fail."""
        # Manually set a higher version
        temp_db._conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION + 1, datetime.now(timezone.utc).isoformat())
        )
        temp_db._conn.commit()
        temp_db.close()
        
        # Try to reopen - should fail
        db2 = DatabaseManager(str(temp_db.db_path))
        
        with pytest.raises(SchemaMismatchError) as exc_info:
            db2.initialize()
        
        assert "newer than code version" in str(exc_info.value)


class TestConversationOperations:
    """Test conversation CRUD operations."""
    
    def test_save_and_get_conversation(self, temp_db):
        """Can save and retrieve a conversation."""
        conv = Conversation(meta={"topic": "test"})
        
        with temp_db.transaction():
            temp_db.save_conversation(conv)
        
        retrieved = temp_db.get_conversation(conv.id)
        
        assert retrieved is not None
        assert retrieved.id == conv.id
        assert retrieved.meta == {"topic": "test"}
    
    def test_get_or_create_new(self, temp_db):
        """get_or_create creates new conversation if not exists."""
        conv = temp_db.get_or_create_conversation()
        
        assert conv.id is not None
        
        # Should persist
        retrieved = temp_db.get_conversation(conv.id)
        assert retrieved is not None
    
    def test_get_or_create_existing(self, temp_db):
        """get_or_create returns existing conversation."""
        conv1 = temp_db.get_or_create_conversation()
        conv2 = temp_db.get_or_create_conversation(conv1.id)
        
        assert conv1.id == conv2.id
    
    def test_list_conversations(self, temp_db):
        """Can list conversations."""
        for i in range(5):
            conv = Conversation()
            with temp_db.transaction():
                temp_db.save_conversation(conv)
        
        convs = temp_db.list_conversations(limit=3)
        
        assert len(convs) == 3


class TestTurnOperations:
    """Test turn CRUD operations."""
    
    def test_save_and_get_turns(self, temp_db):
        """Can save and retrieve turns."""
        conv = temp_db.get_or_create_conversation()
        
        turn1 = Turn(
            conversation_id=conv.id,
            turn_id="turn_abc123",
            role="user",
            content="Hello"
        )
        turn2 = Turn(
            conversation_id=conv.id,
            turn_id="turn_abc123",
            role="assistant",
            content="Hi there!"
        )
        
        with temp_db.transaction():
            temp_db.save_turn(turn1)
            temp_db.save_turn(turn2)
        
        turns = temp_db.get_turns(conv.id)
        
        assert len(turns) == 2
        assert turns[0].content == "Hello"
        assert turns[1].content == "Hi there!"
    
    def test_get_recent_turns(self, temp_db):
        """get_recent_turns returns most recent in correct order."""
        conv = temp_db.get_or_create_conversation()
        
        # Add 10 turns
        for i in range(10):
            turn = Turn(
                conversation_id=conv.id,
                role="user",
                content=f"Message {i}",
                timestamp=datetime.now(timezone.utc) + timedelta(seconds=i)
            )
            with temp_db.transaction():
                temp_db.save_turn(turn)
        
        recent = temp_db.get_recent_turns(conv.id, count=3)
        
        assert len(recent) == 3
        # Should be in chronological order (7, 8, 9)
        assert recent[0].content == "Message 7"
        assert recent[2].content == "Message 9"
    
    def test_turn_id_preserved(self, temp_db):
        """turn_id from logging should be preserved."""
        conv = temp_db.get_or_create_conversation()
        
        turn = Turn(
            conversation_id=conv.id,
            turn_id="turn_unique123",
            role="user",
            content="Test"
        )
        
        with temp_db.transaction():
            temp_db.save_turn(turn)
        
        retrieved = temp_db.get_turns(conv.id)[0]
        assert retrieved.turn_id == "turn_unique123"


class TestMemoryOperations:
    """Test memory CRUD operations."""
    
    def test_save_and_get_memory(self, temp_db):
        """Can save and retrieve memory."""
        memory = Memory(key="user:name", value="Test User")
        
        with temp_db.transaction():
            temp_db.save_memory(memory)
        
        retrieved = temp_db.get_memory("user:name")
        
        assert retrieved is not None
        assert retrieved.value == "Test User"
    
    def test_memory_update(self, temp_db):
        """Saving with same key updates existing."""
        memory1 = Memory(key="counter", value=1)
        memory2 = Memory(key="counter", value=2)
        
        with temp_db.transaction():
            temp_db.save_memory(memory1)
        
        with temp_db.transaction():
            temp_db.save_memory(memory2)
        
        retrieved = temp_db.get_memory("counter")
        assert retrieved.value == 2
    
    def test_delete_memory(self, temp_db):
        """Can delete memory."""
        memory = Memory(key="temp", value="delete me")
        
        with temp_db.transaction():
            temp_db.save_memory(memory)
        
        with temp_db.transaction():
            result = temp_db.delete_memory("temp")
        
        assert result is True
        assert temp_db.get_memory("temp") is None


class TestTaskOperations:
    """Test scheduled task operations."""
    
    def test_save_and_get_pending_tasks(self, temp_db):
        """Can save and retrieve pending tasks."""
        task = ScheduledTask(
            name="Reminder",
            action="remind me",
            scheduled_time=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        
        with temp_db.transaction():
            temp_db.save_task(task)
        
        pending = temp_db.get_pending_tasks()
        
        assert len(pending) == 1
        assert pending[0].name == "Reminder"
    
    def test_update_task_status(self, temp_db):
        """Can update task status."""
        task = ScheduledTask(name="Test", action="test")
        
        with temp_db.transaction():
            temp_db.save_task(task)
        
        with temp_db.transaction():
            temp_db.update_task_status(task.id, "completed")
        
        pending = temp_db.get_pending_tasks()
        assert len(pending) == 0


class TestTransactions:
    """Test transaction behavior."""
    
    def test_transaction_commit(self, temp_db):
        """Successful transactions commit."""
        conv = Conversation()
        
        with temp_db.transaction():
            temp_db.save_conversation(conv)
        
        # Should persist after context exits
        assert temp_db.get_conversation(conv.id) is not None
    
    def test_transaction_rollback_on_error(self, temp_db):
        """Transactions rollback on error."""
        conv = Conversation()
        
        try:
            with temp_db.transaction():
                temp_db.save_conversation(conv)
                raise ValueError("Simulated error")
        except ValueError:
            pass
        
        # Should NOT persist
        assert temp_db.get_conversation(conv.id) is None
    
    def test_nested_operations_in_transaction(self, temp_db):
        """Multiple operations in transaction are atomic."""
        conv = Conversation()
        turn = Turn(
            conversation_id=conv.id,
            role="user",
            content="Hello"
        )
        
        with temp_db.transaction():
            temp_db.save_conversation(conv)
            temp_db.save_turn(turn)
        
        assert temp_db.get_conversation(conv.id) is not None
        assert len(temp_db.get_turns(conv.id)) == 1


class TestRetentionPolicies:
    """Test data retention enforcement."""
    
    def test_turns_pruning_on_startup(self, temp_db):
        """Excess turns are pruned on startup."""
        conv = temp_db.get_or_create_conversation()
        
        # Add more turns than limit
        excess = 10
        for i in range(MAX_TURNS_PER_CONVERSATION + excess):
            turn = Turn(
                conversation_id=conv.id,
                role="user",
                content=f"Message {i}",
                timestamp=datetime.now(timezone.utc) + timedelta(seconds=i)
            )
            temp_db._conn.execute("""
                INSERT INTO turns (id, conversation_id, turn_id, role, content, timestamp, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (turn.id, turn.conversation_id, turn.turn_id, turn.role, 
                  turn.content, turn.timestamp.isoformat(), "{}"))
        temp_db._conn.commit()
        
        # Simulate startup pruning
        temp_db._prune_on_startup()
        
        turns = temp_db.get_turns(conv.id, limit=MAX_TURNS_PER_CONVERSATION + 100)
        assert len(turns) == MAX_TURNS_PER_CONVERSATION


class TestCrashRecovery:
    """Test crash and recovery scenarios."""
    
    def test_partial_write_recovery(self, temp_db):
        """Database should be consistent after partial writes."""
        conv = Conversation()
        
        # Start transaction but don't commit
        temp_db._conn.execute("BEGIN")
        temp_db._conn.execute("""
            INSERT INTO conversations (id, created_at, meta)
            VALUES (?, ?, ?)
        """, (conv.id, datetime.now(timezone.utc).isoformat(), "{}"))
        # Simulate crash - rollback
        temp_db._conn.rollback()
        
        # Data should not exist
        assert temp_db.get_conversation(conv.id) is None
        
        # Database should still be usable
        conv2 = temp_db.get_or_create_conversation()
        assert conv2 is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
