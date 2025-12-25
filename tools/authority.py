"""
Tool Authority System
---------------------
Centralized permission grant management for tool execution.

v0.6.0: Governance release.

Rules:
- No tool executes without explicit grant
- Default grants are pre-approved explicit grants loaded at startup
- Grants can expire or be one-time
- Revoked/expired grants immediately block execution, even mid-session
- All decisions logged with turn_id
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import logging
import yaml

from .registry import PermissionLevel

# Audit logging (v0.7.0)
try:
    from infra.audit import EventType, Actor, audit_event
    _AUDIT_AVAILABLE = True
except ImportError:
    _AUDIT_AVAILABLE = False


class GrantStatus(Enum):
    """Status of a permission grant check."""
    GRANTED = auto()
    DENIED_NO_GRANT = auto()
    DENIED_EXPIRED = auto()
    DENIED_REVOKED = auto()
    DENIED_LEVEL_MISMATCH = auto()
    REQUIRES_CONFIRMATION = auto()


@dataclass
class PermissionGrant:
    """
    A grant of permission to a tool or category.
    
    Grants are explicit approvals for tool execution.
    Default grants loaded at startup are still explicit grants.
    """
    target: str  # Tool name or category (e.g., "get_time" or "READ")
    level: PermissionLevel
    granted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    one_time: bool = False  # Revoke after single use
    revoked: bool = False
    source: str = "default"  # "default", "user", "session"
    
    def is_valid(self) -> bool:
        """Check if grant is currently valid."""
        if self.revoked:
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True
    
    def matches(self, tool_name: str, required_level: PermissionLevel) -> bool:
        """Check if this grant applies to a tool."""
        # Direct tool name match
        if self.target == tool_name:
            return True
        # Category match (grant level covers required level)
        if self.target == required_level.value:
            return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "target": self.target,
            "level": self.level.value,
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "one_time": self.one_time,
            "revoked": self.revoked,
            "source": self.source,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PermissionGrant":
        """Deserialize from storage."""
        return cls(
            target=data["target"],
            level=PermissionLevel(data["level"]),
            granted_at=datetime.fromisoformat(data["granted_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            one_time=data.get("one_time", False),
            revoked=data.get("revoked", False),
            source=data.get("source", "default"),
        )


@dataclass
class AuthorityDecision:
    """
    Result of an authority check.
    
    All decisions are logged with turn_id for auditability.
    """
    status: GrantStatus
    tool_name: str
    required_level: PermissionLevel
    grant_used: Optional[PermissionGrant] = None
    reason: str = ""
    turn_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def allowed(self) -> bool:
        return self.status == GrantStatus.GRANTED
    
    @property
    def needs_confirmation(self) -> bool:
        return self.status == GrantStatus.REQUIRES_CONFIRMATION


class ToolAuthority:
    """
    Central authority for tool permissions.
    
    This is the single choke point for all tool execution authorization.
    
    Rules:
    - No tool executes without explicit grant
    - Default grants are pre-approved explicit grants loaded at startup
    - Grants can expire or be one-time
    - Revoked/expired grants immediately block execution
    - All decisions logged with turn_id
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        db_manager=None
    ):
        self._grants: Dict[str, PermissionGrant] = {}  # key = target
        self._session_grants: Dict[str, PermissionGrant] = {}  # session-only grants
        self._confirmation_required: Set[PermissionLevel] = set()
        self._always_blocked: Set[PermissionLevel] = set()
        self._logger = logging.getLogger("jarvis.tools.authority")
        self._db = db_manager
        
        # Load default grants from config
        if config_path:
            self._load_config(Path(config_path))
        else:
            self._load_default_config()
    
    def _load_config(self, path: Path) -> None:
        """Load permission configuration from YAML."""
        if not path.exists():
            self._logger.warning(f"Permission config not found: {path}")
            self._load_default_config()
            return
        
        try:
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Load default grants
            for grant_def in config.get("default_grants", []):
                grant = PermissionGrant(
                    target=grant_def["target"],
                    level=PermissionLevel(grant_def["level"]),
                    source="default"
                )
                self._grants[grant.target] = grant
                self._logger.debug(f"Loaded default grant: {grant.target}")
            
            # Load confirmation requirements
            for level_str in config.get("requires_confirmation", []):
                self._confirmation_required.add(PermissionLevel(level_str.lower()))
            
            # Load always blocked
            for level_str in config.get("always_blocked", []):
                self._always_blocked.add(PermissionLevel(level_str.lower()))
            
            self._logger.info(
                f"Loaded {len(self._grants)} default grants, "
                f"{len(self._confirmation_required)} confirmation levels"
            )
            
        except Exception as e:
            self._logger.error(f"Failed to load permission config: {e}")
            self._load_default_config()
    
    def _load_default_config(self) -> None:
        """Load hardcoded default configuration."""
        # Default grants for READ-only tools
        default_tools = [
            ("get_current_time", PermissionLevel.READ),
            ("get_current_date", PermissionLevel.READ),
            ("list_scheduled_tasks", PermissionLevel.READ),
            ("list_directory", PermissionLevel.READ),
        ]
        
        for target, level in default_tools:
            self._grants[target] = PermissionGrant(
                target=target,
                level=level,
                source="default"
            )
        
        # Confirmation required for destructive operations
        self._confirmation_required = {
            PermissionLevel.WRITE,
            PermissionLevel.EXECUTE,
            PermissionLevel.NETWORK,
            PermissionLevel.ADMIN,
        }
        
        # Always blocked
        self._always_blocked = {PermissionLevel.ADMIN}
        
        self._logger.info("Loaded default permission configuration")
    
    def check(
        self,
        tool_name: str,
        required_level: PermissionLevel,
        turn_id: Optional[str] = None
    ) -> AuthorityDecision:
        """
        Check if a tool execution is authorized.
        
        This is the main entry point for authorization checks.
        All decisions are logged.
        """
        # Check always blocked first
        if required_level in self._always_blocked:
            decision = AuthorityDecision(
                status=GrantStatus.DENIED_NO_GRANT,
                tool_name=tool_name,
                required_level=required_level,
                reason=f"Permission level {required_level.value} is always blocked",
                turn_id=turn_id
            )
            self._log_decision(decision)
            return decision
        
        # Look for matching grant (session grants take priority)
        grant = self._find_grant(tool_name, required_level)
        
        if grant is None:
            # No grant found - check if confirmation can create one
            if required_level in self._confirmation_required:
                decision = AuthorityDecision(
                    status=GrantStatus.REQUIRES_CONFIRMATION,
                    tool_name=tool_name,
                    required_level=required_level,
                    reason=f"Tool requires user confirmation",
                    turn_id=turn_id
                )
            else:
                decision = AuthorityDecision(
                    status=GrantStatus.DENIED_NO_GRANT,
                    tool_name=tool_name,
                    required_level=required_level,
                    reason=f"No grant found for {tool_name}",
                    turn_id=turn_id
                )
            self._log_decision(decision)
            return decision
        
        # Check grant validity
        if grant.revoked:
            decision = AuthorityDecision(
                status=GrantStatus.DENIED_REVOKED,
                tool_name=tool_name,
                required_level=required_level,
                grant_used=grant,
                reason="Grant has been revoked",
                turn_id=turn_id
            )
            self._log_decision(decision)
            return decision
        
        if not grant.is_valid():
            decision = AuthorityDecision(
                status=GrantStatus.DENIED_EXPIRED,
                tool_name=tool_name,
                required_level=required_level,
                grant_used=grant,
                reason="Grant has expired",
                turn_id=turn_id
            )
            self._log_decision(decision)
            return decision
        
        # Grant is valid - check if confirmation still required
        if required_level in self._confirmation_required and grant.source == "default":
            decision = AuthorityDecision(
                status=GrantStatus.REQUIRES_CONFIRMATION,
                tool_name=tool_name,
                required_level=required_level,
                grant_used=grant,
                reason="Tool requires user confirmation despite default grant",
                turn_id=turn_id
            )
            self._log_decision(decision)
            return decision
        
        # Granted!
        decision = AuthorityDecision(
            status=GrantStatus.GRANTED,
            tool_name=tool_name,
            required_level=required_level,
            grant_used=grant,
            reason="Authorized",
            turn_id=turn_id
        )
        self._log_decision(decision)
        
        # Handle one-time grants
        if grant.one_time:
            self.revoke(grant.target)
        
        return decision
    
    def _find_grant(
        self,
        tool_name: str,
        required_level: PermissionLevel
    ) -> Optional[PermissionGrant]:
        """
        Find a grant that applies to this tool.
        
        Returns the grant even if revoked/expired - caller must check validity.
        This allows returning proper DENIED_REVOKED/DENIED_EXPIRED status.
        """
        # Session grants first (user-approved this session)
        for grant in self._session_grants.values():
            if grant.matches(tool_name, required_level):
                return grant
        
        # Default/persistent grants
        for grant in self._grants.values():
            if grant.matches(tool_name, required_level):
                return grant
        
        return None
    
    def grant(
        self,
        target: str,
        level: PermissionLevel,
        expires_in_seconds: Optional[int] = None,
        one_time: bool = False,
        source: str = "user"
    ) -> PermissionGrant:
        """
        Create a new permission grant.
        
        Session grants are stored separately and cleared on restart.
        """
        expires_at = None
        if expires_in_seconds is not None:  # Allow 0 to mean immediate expiry
            from datetime import timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
        
        grant_obj = PermissionGrant(
            target=target,
            level=level,
            expires_at=expires_at,
            one_time=one_time,
            source=source
        )
        
        if source == "session":
            self._session_grants[target] = grant_obj
        else:
            self._grants[target] = grant_obj
        
        self._logger.info(f"Granted permission: {target} ({level.value})")
        return grant_obj
    
    def revoke(self, target: str) -> bool:
        """
        Revoke a permission grant.
        
        Revocation is immediate - even mid-session.
        """
        revoked = False
        
        if target in self._session_grants:
            self._session_grants[target].revoked = True
            revoked = True
        
        if target in self._grants:
            self._grants[target].revoked = True
            revoked = True
        
        if revoked:
            self._logger.info(f"Revoked permission: {target}")
        
        return revoked
    
    def clear_session_grants(self) -> int:
        """Clear all session grants. Called on shutdown."""
        count = len(self._session_grants)
        self._session_grants.clear()
        self._logger.info(f"Cleared {count} session grants")
        return count
    
    def list_grants(self, include_revoked: bool = False) -> List[PermissionGrant]:
        """List all grants."""
        all_grants = list(self._grants.values()) + list(self._session_grants.values())
        if not include_revoked:
            all_grants = [g for g in all_grants if not g.revoked]
        return all_grants
    
    def _log_decision(self, decision: AuthorityDecision) -> None:
        """Log an authority decision for audit."""
        level = logging.INFO if decision.allowed else logging.WARNING
        
        self._logger.log(
            level,
            f"Authority decision: {decision.status.name} | "
            f"tool={decision.tool_name} | "
            f"level={decision.required_level.value} | "
            f"reason={decision.reason} | "
            f"turn_id={decision.turn_id or 'N/A'}"
        )
        
        # v0.7.0: Immutable audit log
        if _AUDIT_AVAILABLE and decision.turn_id:
            audit_event(
                event_type=EventType.AUTHORITY_CHECK,
                actor=Actor.AUTHORITY,
                action=decision.status.name.lower(),
                turn_id=decision.turn_id,
                target=decision.tool_name,
                details={
                    "required_level": decision.required_level.value,
                    "reason": decision.reason,
                    "granted": decision.allowed
                }
            )
