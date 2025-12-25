"""
Immutable Audit Log
-------------------
HMAC-chained audit trail for accountability guarantees.

v0.7.0: Accountability release.

Trust Boundary:
- Tamper-evident, NOT tamper-proof
- Assumes HMAC key protected at OS/process boundary
- Attacker with DB + key access can recompute chain

Design:
- Append-only (no UPDATE, no DELETE in code)
- HMAC chain for ordering integrity
- Canonical JSON serialization for determinism
- turn_id for full traceability
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import uuid


class EventType(str, Enum):
    """Audit event types."""
    TURN_START = "TURN_START"
    TURN_END = "TURN_END"
    PLAN_CREATED = "PLAN_CREATED"
    AUTHORITY_CHECK = "AUTHORITY_CHECK"
    CONFIRM_REQUEST = "CONFIRM_REQUEST"
    CONFIRM_RESPONSE = "CONFIRM_RESPONSE"
    TOOL_EXECUTE = "TOOL_EXECUTE"
    MEMORY_DELETE = "MEMORY_DELETE"
    MEMORY_REDACT = "MEMORY_REDACT"
    GRANT_CREATED = "GRANT_CREATED"
    GRANT_REVOKED = "GRANT_REVOKED"


class Actor(str, Enum):
    """Audit actors."""
    USER = "user"
    PLANNER = "planner"
    AUTHORITY = "authority"
    EXECUTOR = "executor"
    GOVERNOR = "governor"
    SYSTEM = "system"


@dataclass
class AuditEntry:
    """
    A single audit log entry.
    
    Each entry contains:
    - turn_id for traceability
    - Event details (type, actor, action, target)
    - prev_hash for chain integrity
    - entry_hash (HMAC) for tamper detection
    """
    id: Optional[int] = None  # Database ID
    turn_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: EventType = EventType.TURN_START
    actor: Actor = Actor.SYSTEM
    action: str = ""
    target: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    prev_hash: str = ""
    entry_hash: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "id": self.id,
            "turn_id": self.turn_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else self.event_type,
            "actor": self.actor.value if isinstance(self.actor, Actor) else self.actor,
            "action": self.action,
            "target": self.target,
            "details": json.dumps(self.details, sort_keys=True) if self.details else None,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AuditEntry":
        """Deserialize from database row."""
        details = None
        if row["details"]:
            try:
                details = json.loads(row["details"])
            except json.JSONDecodeError:
                details = {"_raw": row["details"]}
        
        return cls(
            id=row["id"],
            turn_id=row["turn_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            event_type=EventType(row["event_type"]),
            actor=Actor(row["actor"]),
            action=row["action"],
            target=row["target"],
            details=details,
            prev_hash=row["prev_hash"] or "",
            entry_hash=row["entry_hash"],
        )


@dataclass
class VerifyResult:
    """Result of chain verification."""
    valid: bool
    entries_checked: int
    broken_at: Optional[int] = None  # Entry ID where chain broke
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    error: Optional[str] = None


class AuditLog:
    """
    Immutable audit log with HMAC chain verification.
    
    Guarantees:
    - Append-only (no updates, no deletes in code)
    - Chain integrity verifiable
    - Full turn reconstruction
    
    Trust Boundary:
    - Tamper-evident assuming HMAC key is secret
    - Key stored in environment, never in database
    """
    
    # Genesis hash for first entry
    GENESIS_HASH = "0" * 64
    
    def __init__(self, db_path: str = "jarvis.db", key: Optional[bytes] = None):
        self._db_path = db_path
        self._logger = logging.getLogger("jarvis.infra.audit")
        
        # HMAC key management
        self._key = key or self._load_key()
        
        # Initialize schema
        self._ensure_schema()
    
    def _load_key(self) -> bytes:
        """
        Load HMAC key from environment or derive from machine ID.
        
        Key Management:
        - Primary: JARVIS_AUDIT_KEY environment variable
        - Fallback: Derived from machine-specific data
        - Never stored in database
        """
        # Try environment first
        env_key = os.environ.get("JARVIS_AUDIT_KEY")
        if env_key:
            return env_key.encode('utf-8')
        
        # Fallback: derive from machine ID
        # This is NOT cryptographically strong, but provides
        # machine-specific determinism for testing/development
        import platform
        machine_id = f"{platform.node()}-{platform.machine()}-jarvis-audit"
        return hashlib.sha256(machine_id.encode()).digest()
    
    def _ensure_schema(self) -> None:
        """Create audit_log table if not exists."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT,
                    details TEXT,
                    prev_hash TEXT,
                    entry_hash TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_turn_id 
                ON audit_log(turn_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp 
                ON audit_log(timestamp)
            """)
            conn.commit()
            self._logger.debug("Audit log schema ensured")
        finally:
            conn.close()
    
    def _canonical_payload(self, entry: AuditEntry, prev_hash: str) -> bytes:
        """
        Canonical serialization for HMAC input.
        
        Rules:
        - Fixed field order
        - JSON with sorted keys for details
        - Explicit UTF-8 encoding
        """
        payload = {
            "prev_hash": prev_hash,
            "turn_id": entry.turn_id,
            "timestamp": entry.timestamp.isoformat(),
            "event_type": entry.event_type.value if isinstance(entry.event_type, EventType) else entry.event_type,
            "actor": entry.actor.value if isinstance(entry.actor, Actor) else entry.actor,
            "action": entry.action,
            "target": entry.target,
            "details": entry.details,
        }
        return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    
    def _compute_hash(self, entry: AuditEntry, prev_hash: str) -> str:
        """Compute HMAC-SHA256 for entry."""
        payload = self._canonical_payload(entry, prev_hash)
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()
    
    def _get_last_hash(self, conn: sqlite3.Connection) -> str:
        """Get the hash of the last entry, or genesis hash."""
        cursor = conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row[0] if row else self.GENESIS_HASH
    
    def log(
        self,
        event_type: EventType,
        actor: Actor,
        action: str,
        turn_id: str,
        target: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Append an entry to the audit log.
        
        Returns the entry_hash.
        """
        entry = AuditEntry(
            turn_id=turn_id,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            actor=actor,
            action=action,
            target=target,
            details=details,
        )
        
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Get previous hash (must be atomic with insert)
            prev_hash = self._get_last_hash(conn)
            entry.prev_hash = prev_hash
            
            # Compute entry hash
            entry.entry_hash = self._compute_hash(entry, prev_hash)
            
            # Insert
            cursor = conn.execute("""
                INSERT INTO audit_log 
                (turn_id, timestamp, event_type, actor, action, target, details, prev_hash, entry_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.turn_id,
                entry.timestamp.isoformat(),
                entry.event_type.value if isinstance(entry.event_type, EventType) else entry.event_type,
                entry.actor.value if isinstance(entry.actor, Actor) else entry.actor,
                entry.action,
                entry.target,
                json.dumps(entry.details, sort_keys=True) if entry.details else None,
                entry.prev_hash,
                entry.entry_hash,
            ))
            conn.commit()
            
            entry.id = cursor.lastrowid
            
            self._logger.debug(
                f"Audit: {entry.event_type.value} | {entry.actor.value} | "
                f"{entry.action} | turn={entry.turn_id[:8]}..."
            )
            
            return entry.entry_hash
            
        finally:
            conn.close()
    
    def get_turn_trail(self, turn_id: str) -> List[AuditEntry]:
        """Get all entries for a specific turn."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM audit_log WHERE turn_id = ? ORDER BY id",
                (turn_id,)
            )
            return [AuditEntry.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_entries(
        self,
        from_id: int = 1,
        to_id: Optional[int] = None,
        limit: int = 1000
    ) -> List[AuditEntry]:
        """Get entries in a range."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            if to_id:
                cursor = conn.execute(
                    "SELECT * FROM audit_log WHERE id >= ? AND id <= ? ORDER BY id LIMIT ?",
                    (from_id, to_id, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM audit_log WHERE id >= ? ORDER BY id LIMIT ?",
                    (from_id, limit)
                )
            return [AuditEntry.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def verify_chain(
        self,
        from_id: int = 1,
        to_id: Optional[int] = None
    ) -> VerifyResult:
        """
        Verify HMAC chain integrity.
        
        Returns VerifyResult with:
        - valid: True if chain is intact
        - broken_at: Entry ID where chain broke (if any)
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Get entries
            if to_id:
                cursor = conn.execute(
                    "SELECT * FROM audit_log WHERE id >= ? AND id <= ? ORDER BY id",
                    (from_id, to_id)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM audit_log WHERE id >= ? ORDER BY id",
                    (from_id,)
                )
            
            entries = [AuditEntry.from_row(row) for row in cursor.fetchall()]
            
            if not entries:
                return VerifyResult(valid=True, entries_checked=0)
            
            # Get hash before first entry
            if from_id == 1:
                expected_prev_hash = self.GENESIS_HASH
            else:
                prev_cursor = conn.execute(
                    "SELECT entry_hash FROM audit_log WHERE id = ?",
                    (from_id - 1,)
                )
                prev_row = prev_cursor.fetchone()
                expected_prev_hash = prev_row[0] if prev_row else self.GENESIS_HASH
            
            # Verify each entry
            for entry in entries:
                # Check prev_hash matches expected
                if entry.prev_hash != expected_prev_hash:
                    return VerifyResult(
                        valid=False,
                        entries_checked=entries.index(entry),
                        broken_at=entry.id,
                        expected_hash=expected_prev_hash,
                        actual_hash=entry.prev_hash,
                        error=f"prev_hash mismatch at entry {entry.id}"
                    )
                
                # Verify entry_hash
                computed = self._compute_hash(entry, entry.prev_hash)
                if entry.entry_hash != computed:
                    return VerifyResult(
                        valid=False,
                        entries_checked=entries.index(entry),
                        broken_at=entry.id,
                        expected_hash=computed,
                        actual_hash=entry.entry_hash,
                        error=f"entry_hash mismatch at entry {entry.id}"
                    )
                
                # Update expected for next iteration
                expected_prev_hash = entry.entry_hash
            
            return VerifyResult(
                valid=True,
                entries_checked=len(entries)
            )
            
        finally:
            conn.close()
    
    def export_for_review(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> str:
        """
        Export entries as JSON bundle with verification metadata.
        
        Bundle includes:
        - All entries in range
        - Final entry_hash for chain verification
        - Verification metadata (key ID, not key itself)
        
        Verification requires access to HMAC key.
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            if start and end:
                cursor = conn.execute(
                    "SELECT * FROM audit_log WHERE timestamp >= ? AND timestamp <= ? ORDER BY id",
                    (start.isoformat(), end.isoformat())
                )
            else:
                cursor = conn.execute("SELECT * FROM audit_log ORDER BY id")
            
            entries = [AuditEntry.from_row(row) for row in cursor.fetchall()]
            
            # Build export bundle
            bundle = {
                "version": "0.7.0",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "entry_count": len(entries),
                "first_entry_id": entries[0].id if entries else None,
                "last_entry_id": entries[-1].id if entries else None,
                "final_hash": entries[-1].entry_hash if entries else None,
                "key_id": hashlib.sha256(self._key).hexdigest()[:16],  # Key fingerprint only
                "entries": [e.to_dict() for e in entries],
            }
            
            return json.dumps(bundle, indent=2, sort_keys=True)
            
        finally:
            conn.close()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get audit log statistics."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("SELECT COUNT(*) as count FROM audit_log")
            count = cursor.fetchone()["count"]
            
            cursor = conn.execute(
                "SELECT MIN(timestamp) as first, MAX(timestamp) as last FROM audit_log"
            )
            row = cursor.fetchone()
            
            return {
                "total_entries": count,
                "first_entry": row["first"],
                "last_entry": row["last"],
            }
        finally:
            conn.close()


# Convenience function for quick logging
_default_audit_log: Optional[AuditLog] = None


def get_audit_log(db_path: str = "jarvis.db") -> AuditLog:
    """Get or create the default audit log instance."""
    global _default_audit_log
    if _default_audit_log is None:
        _default_audit_log = AuditLog(db_path=db_path)
    return _default_audit_log


def audit_event(
    event_type: EventType,
    actor: Actor,
    action: str,
    turn_id: str,
    target: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """Quick audit logging function."""
    return get_audit_log().log(
        event_type=event_type,
        actor=actor,
        action=action,
        turn_id=turn_id,
        target=target,
        details=details,
    )
