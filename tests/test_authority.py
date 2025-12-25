"""
Tool Authority Tests
---------------------
Tests for v0.6.0 permission grant system.

Tests cover:
- Grant creation and matching
- Expiry behavior
- One-time grants
- Revocation (immediate block)
- Decision logging
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.authority import (
    ToolAuthority, PermissionGrant, AuthorityDecision, GrantStatus
)
from tools.registry import PermissionLevel


class TestPermissionGrant:
    """Tests for PermissionGrant dataclass."""
    
    def test_grant_creation(self):
        """Grant can be created with required fields."""
        grant = PermissionGrant(
            target="get_current_time",
            level=PermissionLevel.READ
        )
        assert grant.target == "get_current_time"
        assert grant.level == PermissionLevel.READ
        assert grant.is_valid()
    
    def test_grant_expiry(self):
        """Expired grant is invalid."""
        grant = PermissionGrant(
            target="test_tool",
            level=PermissionLevel.READ,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1)  # Past
        )
        assert not grant.is_valid()
    
    def test_grant_not_expired(self):
        """Non-expired grant is valid."""
        grant = PermissionGrant(
            target="test_tool",
            level=PermissionLevel.READ,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)  # Future
        )
        assert grant.is_valid()
    
    def test_revoked_grant_invalid(self):
        """Revoked grant is invalid."""
        grant = PermissionGrant(
            target="test_tool",
            level=PermissionLevel.READ,
            revoked=True
        )
        assert not grant.is_valid()
    
    def test_grant_matches_tool_name(self):
        """Grant matches by exact tool name."""
        grant = PermissionGrant(
            target="get_current_time",
            level=PermissionLevel.READ
        )
        assert grant.matches("get_current_time", PermissionLevel.READ)
        assert not grant.matches("other_tool", PermissionLevel.READ)
    
    def test_grant_serialization(self):
        """Grant can be serialized and deserialized."""
        grant = PermissionGrant(
            target="test_tool",
            level=PermissionLevel.WRITE,
            one_time=True,
            source="user"
        )
        
        data = grant.to_dict()
        restored = PermissionGrant.from_dict(data)
        
        assert restored.target == grant.target
        assert restored.level == grant.level
        assert restored.one_time == grant.one_time
        assert restored.source == grant.source


class TestToolAuthority:
    """Tests for ToolAuthority permission system."""
    
    @pytest.fixture
    def authority(self):
        """Create authority with default config."""
        return ToolAuthority()
    
    def test_default_grants_loaded(self, authority):
        """Default grants are loaded at startup."""
        grants = authority.list_grants()
        assert len(grants) > 0
        
        # Check that default READ tools are granted
        targets = [g.target for g in grants]
        assert "get_current_time" in targets
    
    def test_read_tool_granted(self, authority):
        """READ tool with default grant is allowed."""
        decision = authority.check("get_current_time", PermissionLevel.READ)
        
        # Should be granted (default grant exists)
        assert decision.status == GrantStatus.GRANTED
        assert decision.allowed
    
    def test_write_tool_requires_confirmation(self, authority):
        """WRITE tool without grant requires confirmation."""
        decision = authority.check("some_write_tool", PermissionLevel.WRITE)
        
        assert decision.status == GrantStatus.REQUIRES_CONFIRMATION
        assert decision.needs_confirmation
    
    def test_admin_tool_denied(self, authority):
        """ADMIN tools are always denied."""
        decision = authority.check("admin_tool", PermissionLevel.ADMIN)
        
        assert decision.status == GrantStatus.DENIED_NO_GRANT
        assert not decision.allowed
    
    def test_grant_and_check(self, authority):
        """Can grant permission and use it."""
        # Initially no grant
        decision = authority.check("custom_tool", PermissionLevel.WRITE)
        assert not decision.allowed or decision.needs_confirmation
        
        # Grant permission
        authority.grant(
            target="custom_tool",
            level=PermissionLevel.WRITE,
            source="session"
        )
        
        # Now should be granted
        decision = authority.check("custom_tool", PermissionLevel.WRITE)
        assert decision.allowed
    
    def test_revoke_blocks_immediately(self, authority):
        """Revocation blocks execution immediately."""
        # Grant permission
        authority.grant(
            target="temp_tool",
            level=PermissionLevel.READ,
            source="session"
        )
        
        # Verify granted
        decision = authority.check("temp_tool", PermissionLevel.READ)
        assert decision.allowed
        
        # Revoke
        authority.revoke("temp_tool")
        
        # Now blocked
        decision = authority.check("temp_tool", PermissionLevel.READ)
        assert decision.status == GrantStatus.DENIED_REVOKED
        assert not decision.allowed
    
    def test_one_time_grant(self, authority):
        """One-time grant is revoked after use."""
        authority.grant(
            target="one_time_tool",
            level=PermissionLevel.READ,
            one_time=True,
            source="session"
        )
        
        # First check uses the grant
        decision = authority.check("one_time_tool", PermissionLevel.READ)
        assert decision.allowed
        
        # Grant should now be revoked
        decision = authority.check("one_time_tool", PermissionLevel.READ)
        assert not decision.allowed or decision.needs_confirmation
    
    def test_expiring_grant(self, authority):
        """Grant with expiry blocks after expiration."""
        # Grant for 0 seconds (already expired)
        authority.grant(
            target="expiring_tool",
            level=PermissionLevel.READ,
            expires_in_seconds=0,
            source="session"
        )
        
        # Should be expired
        import time
        time.sleep(0.1)
        
        decision = authority.check("expiring_tool", PermissionLevel.READ)
        assert decision.status == GrantStatus.DENIED_EXPIRED
    
    def test_turn_id_in_decision(self, authority):
        """Decision includes turn_id for auditability."""
        decision = authority.check(
            "get_current_time",
            PermissionLevel.READ,
            turn_id="test-turn-123"
        )
        
        assert decision.turn_id == "test-turn-123"
    
    def test_clear_session_grants(self, authority):
        """Session grants can be cleared."""
        authority.grant(
            target="session_tool",
            level=PermissionLevel.READ,
            source="session"
        )
        
        count = authority.clear_session_grants()
        assert count >= 1
        
        # Session grant should be gone
        grants = authority.list_grants()
        session_targets = [g.target for g in grants if g.source == "session"]
        assert "session_tool" not in session_targets


class TestToolAuthorityConfig:
    """Tests for loading configuration from YAML."""
    
    def test_load_from_yaml(self):
        """Authority loads grants from YAML config."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""
default_grants:
  - target: "custom_read_tool"
    level: read

requires_confirmation:
  - write
  - execute

always_blocked:
  - admin
""")
            temp_path = f.name
        
        try:
            authority = ToolAuthority(config_path=temp_path)
            
            # Custom tool should be granted
            decision = authority.check("custom_read_tool", PermissionLevel.READ)
            assert decision.allowed
            
            # WRITE should require confirmation
            decision = authority.check("other_tool", PermissionLevel.WRITE)
            assert decision.needs_confirmation
            
        finally:
            import os
            os.unlink(temp_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
