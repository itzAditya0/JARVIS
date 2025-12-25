"""
JARVIS Database Manager
-----------------------
SQLite-based persistence layer with schema versioning and retention policies.

Design:
- Schema version table for migrations
- Hard fail on downgrade (db.version > code.version)
- Auto-migrate forward (db.version < code.version)
- Startup-only pruning for v0.5.0
- Explicit transaction boundaries

Usage:
    from infra.database import DatabaseManager
    
    db = DatabaseManager()
    db.initialize()  # Creates/migrates DB
    
    # Write operations
    with db.transaction():
        db.save_conversation(conv)
        db.save_turn(turn)
    
    # Read operations (no transaction needed)
    turns = db.get_turns(conversation_id)
"""

import sqlite3
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Generator

from infra.logging import get_logger

# Current schema version - increment on any schema change
SCHEMA_VERSION = 1

# Retention limits
MAX_TURNS_PER_CONVERSATION = 1000
MAX_CONVERSATIONS = 100


@dataclass
class Conversation:
    """A conversation session."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Turn:
    """A single turn in a conversation."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    turn_id: str = ""  # Logging turn_id for traceability
    role: str = ""  # "user" or "assistant"
    content: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Memory:
    """A key-value memory entry."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    key: str = ""
    value: Any = None
    embedding: Optional[bytes] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ScheduledTask:
    """A scheduled task record."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    action: str = ""
    status: str = "pending"  # pending, completed, cancelled
    scheduled_time: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DatabaseError(Exception):
    """Database-specific errors."""
    pass


class SchemaMismatchError(DatabaseError):
    """Schema version mismatch (downgrade attempted)."""
    pass


class MigrationFailedError(DatabaseError):
    """Migration failed mid-way."""
    pass


class DatabaseManager:
    """
    SQLite database manager with schema versioning.
    
    Thread-safe for reads. Writes should use transaction() context manager.
    """
    
    def __init__(self, db_path: str = "jarvis.db"):
        self._db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._logger = get_logger("infra.database")
        self._initialized = False
        self._in_transaction = False  # Track transaction state

    
    @property
    def db_path(self) -> Path:
        """Return the database file path."""
        return self._db_path
    
    def initialize(self) -> None:
        """
        Initialize the database.
        
        - Creates database if not exists
        - Checks schema version
        - Runs migrations if needed (forward only)
        - Hard fails on downgrade
        - Runs startup pruning
        """
        self._logger.info(f"Initializing database at {self._db_path}")
        
        # Create connection
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        
        # Enable foreign keys
        self._conn.execute("PRAGMA foreign_keys = ON")
        
        # Check/create schema
        db_version = self._get_schema_version()
        
        if db_version is None:
            # Fresh database
            self._logger.info("Creating new database schema")
            self._create_schema()
            self._set_schema_version(SCHEMA_VERSION)
        elif db_version < SCHEMA_VERSION:
            # Need migration
            self._logger.info(f"Migrating database from v{db_version} to v{SCHEMA_VERSION}")
            self._migrate(db_version, SCHEMA_VERSION)
        elif db_version > SCHEMA_VERSION:
            # Downgrade not allowed
            raise SchemaMismatchError(
                f"Database schema version ({db_version}) is newer than code version ({SCHEMA_VERSION}). "
                f"Downgrade is not supported. Please update the code or use a different database."
            )
        else:
            self._logger.info(f"Database schema is up to date (v{db_version})")
        
        # Run startup pruning
        self._prune_on_startup()
        
        # Verify integrity
        self._verify_integrity()
        
        self._initialized = True
        self._logger.info("Database initialized successfully")
    
    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._initialized = False
    
    def _get_schema_version(self) -> Optional[int]:
        """Get the current schema version from the database."""
        try:
            cursor = self._conn.execute(
                "SELECT version FROM schema_version ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row["version"] if row else None
        except sqlite3.OperationalError:
            # Table doesn't exist
            return None
    
    def _set_schema_version(self, version: int) -> None:
        """Set the schema version."""
        self._conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, datetime.now(timezone.utc).isoformat())
        )
        self._conn.commit()
    
    def _create_schema(self) -> None:
        """Create the initial database schema (v1)."""
        schema_sql = """
        -- Schema version tracking
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL
        );
        
        -- Conversations
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            meta TEXT DEFAULT '{}'
        );
        
        -- Turns within conversations
        CREATE TABLE IF NOT EXISTS turns (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            turn_id TEXT,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            meta TEXT DEFAULT '{}',
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_turns_conversation ON turns(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);
        
        -- Key-value memories
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            embedding BLOB,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
        
        -- Scheduled tasks
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending', 'completed', 'cancelled')),
            scheduled_time TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        """
        
        self._conn.executescript(schema_sql)
        self._conn.commit()
    
    def _migrate(self, from_version: int, to_version: int) -> None:
        """
        Run migrations from one version to another.
        
        Each migration is atomic. If any migration fails, the entire
        operation is aborted and the database is left at the last
        successful version.
        """
        migrations = {
            # Example: 1 -> 2 migration
            # 2: "ALTER TABLE conversations ADD COLUMN archived INTEGER DEFAULT 0;"
        }
        
        for version in range(from_version + 1, to_version + 1):
            if version in migrations:
                self._logger.info(f"Applying migration to v{version}")
                try:
                    self._conn.executescript(migrations[version])
                    self._set_schema_version(version)
                except Exception as e:
                    raise MigrationFailedError(
                        f"Migration to v{version} failed: {e}. "
                        f"Database is at v{from_version}. Manual intervention required."
                    )
            else:
                # No migration needed, just update version
                self._set_schema_version(version)
    
    def _prune_on_startup(self) -> None:
        """
        Prune old data on startup to enforce retention policies.
        
        v0.5.0: Startup-only pruning, no background/cron.
        """
        self._logger.info("Running startup pruning")
        
        # Prune excess turns per conversation
        cursor = self._conn.execute("""
            SELECT conversation_id, COUNT(*) as turn_count
            FROM turns
            GROUP BY conversation_id
            HAVING turn_count > ?
        """, (MAX_TURNS_PER_CONVERSATION,))
        
        for row in cursor.fetchall():
            conv_id = row["conversation_id"]
            excess = row["turn_count"] - MAX_TURNS_PER_CONVERSATION
            
            # Delete oldest turns
            self._conn.execute("""
                DELETE FROM turns
                WHERE id IN (
                    SELECT id FROM turns
                    WHERE conversation_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                )
            """, (conv_id, excess))
            
            self._logger.info(f"Pruned {excess} turns from conversation {conv_id[:8]}...")
        
        # Prune excess conversations (keep newest)
        cursor = self._conn.execute("SELECT COUNT(*) as count FROM conversations")
        conv_count = cursor.fetchone()["count"]
        
        if conv_count > MAX_CONVERSATIONS:
            excess = conv_count - MAX_CONVERSATIONS
            self._conn.execute("""
                DELETE FROM conversations
                WHERE id IN (
                    SELECT id FROM conversations
                    ORDER BY created_at ASC
                    LIMIT ?
                )
            """, (excess,))
            self._logger.info(f"Pruned {excess} old conversations")
        
        self._conn.commit()
    
    def _verify_integrity(self) -> None:
        """Verify database integrity."""
        cursor = self._conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()[0]
        
        if result != "ok":
            raise DatabaseError(f"Database integrity check failed: {result}")
    
    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """
        Context manager for explicit transactions.
        
        Supports simple nesting - inner transactions are no-ops if already in transaction.
        
        Usage:
            with db.transaction():
                db.save_conversation(conv)
                db.save_turn(turn)
        """
        if not self._initialized:
            raise DatabaseError("Database not initialized. Call initialize() first.")
        
        # If already in a transaction, just yield (nested call)
        if self._in_transaction:
            yield
            return
        
        self._in_transaction = True
        try:
            yield
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            self._logger.error(f"Transaction rolled back: {e}")
            raise
        finally:
            self._in_transaction = False

    
    # ===== Conversation Operations =====
    
    def save_conversation(self, conv: Conversation) -> None:
        """Save or update a conversation."""
        self._conn.execute("""
            INSERT OR REPLACE INTO conversations (id, created_at, meta)
            VALUES (?, ?, ?)
        """, (
            conv.id,
            conv.created_at.isoformat(),
            json.dumps(conv.meta)
        ))
    
    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        """Get a conversation by ID."""
        cursor = self._conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conv_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Conversation(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            meta=json.loads(row["meta"] or "{}")
        )
    
    def get_or_create_conversation(self, conv_id: Optional[str] = None) -> Conversation:
        """Get an existing conversation or create a new one."""
        if conv_id:
            conv = self.get_conversation(conv_id)
            if conv:
                return conv
        
        conv = Conversation(id=conv_id or str(uuid.uuid4()))
        self.save_conversation(conv)
        self._conn.commit()  # Auto-commit for convenience method
        return conv

    
    def list_conversations(self, limit: int = 10) -> List[Conversation]:
        """List recent conversations."""
        cursor = self._conn.execute(
            "SELECT * FROM conversations ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        
        return [
            Conversation(
                id=row["id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                meta=json.loads(row["meta"] or "{}")
            )
            for row in cursor.fetchall()
        ]
    
    # ===== Turn Operations =====
    
    def save_turn(self, turn: Turn) -> None:
        """Save a turn."""
        self._conn.execute("""
            INSERT OR REPLACE INTO turns (id, conversation_id, turn_id, role, content, timestamp, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            turn.id,
            turn.conversation_id,
            turn.turn_id,
            turn.role,
            turn.content,
            turn.timestamp.isoformat(),
            json.dumps(turn.meta)
        ))
    
    def get_turns(
        self,
        conversation_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Turn]:
        """Get turns for a conversation."""
        cursor = self._conn.execute("""
            SELECT * FROM turns
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
            LIMIT ? OFFSET ?
        """, (conversation_id, limit, offset))
        
        return [
            Turn(
                id=row["id"],
                conversation_id=row["conversation_id"],
                turn_id=row["turn_id"] or "",
                role=row["role"],
                content=row["content"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                meta=json.loads(row["meta"] or "{}")
            )
            for row in cursor.fetchall()
        ]
    
    def get_recent_turns(self, conversation_id: str, count: int = 10) -> List[Turn]:
        """Get the most recent turns (for context window)."""
        cursor = self._conn.execute("""
            SELECT * FROM (
                SELECT * FROM turns
                WHERE conversation_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ) ORDER BY timestamp ASC
        """, (conversation_id, count))
        
        return [
            Turn(
                id=row["id"],
                conversation_id=row["conversation_id"],
                turn_id=row["turn_id"] or "",
                role=row["role"],
                content=row["content"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                meta=json.loads(row["meta"] or "{}")
            )
            for row in cursor.fetchall()
        ]
    
    # ===== Memory Operations =====
    
    def save_memory(self, memory: Memory) -> None:
        """Save or update a memory entry."""
        self._conn.execute("""
            INSERT OR REPLACE INTO memories (id, key, value, embedding, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            memory.id,
            memory.key,
            json.dumps(memory.value) if memory.value is not None else None,
            memory.embedding,
            memory.created_at.isoformat(),
            datetime.now(timezone.utc).isoformat()
        ))
    
    def get_memory(self, key: str) -> Optional[Memory]:
        """Get a memory by key."""
        cursor = self._conn.execute(
            "SELECT * FROM memories WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Memory(
            id=row["id"],
            key=row["key"],
            value=json.loads(row["value"]) if row["value"] else None,
            embedding=row["embedding"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
    
    def delete_memory(self, key: str) -> bool:
        """Delete a memory by key."""
        cursor = self._conn.execute(
            "DELETE FROM memories WHERE key = ?",
            (key,)
        )
        return cursor.rowcount > 0
    
    # ===== Task Operations =====
    
    def save_task(self, task: ScheduledTask) -> None:
        """Save or update a scheduled task."""
        self._conn.execute("""
            INSERT OR REPLACE INTO tasks (id, name, action, status, scheduled_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            task.id,
            task.name,
            task.action,
            task.status,
            task.scheduled_time.isoformat() if task.scheduled_time else None,
            task.created_at.isoformat()
        ))
    
    def get_pending_tasks(self) -> List[ScheduledTask]:
        """Get all pending tasks."""
        cursor = self._conn.execute(
            "SELECT * FROM tasks WHERE status = 'pending' ORDER BY scheduled_time ASC"
        )
        
        return [
            ScheduledTask(
                id=row["id"],
                name=row["name"],
                action=row["action"],
                status=row["status"],
                scheduled_time=datetime.fromisoformat(row["scheduled_time"]) if row["scheduled_time"] else None,
                created_at=datetime.fromisoformat(row["created_at"])
            )
            for row in cursor.fetchall()
        ]
    
    def update_task_status(self, task_id: str, status: str) -> bool:
        """Update a task's status."""
        cursor = self._conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status, task_id)
        )
        return cursor.rowcount > 0
