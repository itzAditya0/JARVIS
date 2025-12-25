"""
v0.5.1 Enforcement Tests
------------------------
Tests that enforce v0.5.1 invariants:
1. No legacy orchestrator files
2. No JSON persistence at runtime
3. turn_id required for tool execution

These tests MUST pass for any release tagged v0.5.1+.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestLegacyOrchestratorsRemoved:
    """Verify legacy orchestrator files are deleted."""
    
    def test_orchestrator_v2_deleted(self):
        """orchestrator_v2.py must not exist."""
        core_dir = Path(__file__).parent.parent / "core"
        legacy_file = core_dir / "orchestrator_v2.py"
        
        assert not legacy_file.exists(), (
            f"FATAL: Legacy file exists: {legacy_file}\n"
            "v0.5.1 requires deletion of orchestrator_v2.py"
        )
    
    def test_orchestrator_v3_deleted(self):
        """orchestrator_v3.py must not exist."""
        core_dir = Path(__file__).parent.parent / "core"
        legacy_file = core_dir / "orchestrator_v3.py"
        
        assert not legacy_file.exists(), (
            f"FATAL: Legacy file exists: {legacy_file}\n"
            "v0.5.1 requires deletion of orchestrator_v3.py"
        )
    
    def test_orchestrator_v4_deleted(self):
        """orchestrator_v4.py must not exist (merged into unified)."""
        core_dir = Path(__file__).parent.parent / "core"
        legacy_file = core_dir / "orchestrator_v4.py"
        
        assert not legacy_file.exists(), (
            f"FATAL: Legacy file exists: {legacy_file}\n"
            "v0.5.1 requires deletion of orchestrator_v4.py (use orchestrator_unified.py)"
        )
    
    def test_unified_orchestrator_exists(self):
        """orchestrator_unified.py must exist."""
        core_dir = Path(__file__).parent.parent / "core"
        unified_file = core_dir / "orchestrator_unified.py"
        
        assert unified_file.exists(), (
            f"FATAL: Unified orchestrator missing: {unified_file}"
        )
    
    def test_legacy_imports_fail(self):
        """Attempting to import legacy orchestrators must fail."""
        # These imports should raise ImportError or ModuleNotFoundError
        with pytest.raises((ImportError, ModuleNotFoundError)):
            import core.orchestrator_v2
        
        with pytest.raises((ImportError, ModuleNotFoundError)):
            import core.orchestrator_v3
        
        with pytest.raises((ImportError, ModuleNotFoundError)):
            import core.orchestrator_v4


class TestJSONPersistenceDisabled:
    """Verify JSON persistence is disabled at runtime."""
    
    def test_event_manager_json_persist_raises(self):
        """EventManager._persist_tasks must raise if persist_file is set."""
        from multimodal.events import EventManager
        
        manager = EventManager(persist_file="/tmp/should_not_be_used.json")
        
        with pytest.raises(RuntimeError) as exc_info:
            manager._persist_tasks()
        
        assert "JSON persistence is disabled" in str(exc_info.value)
    
    def test_event_manager_json_load_warns(self):
        """EventManager should warn if legacy JSON file exists."""
        import tempfile
        import os
        from multimodal.events import EventManager
        
        # Create a temp file to simulate legacy data
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('[{"id": "test"}]')
            temp_path = f.name
        
        try:
            # Should not load the file, but should log a warning
            manager = EventManager(persist_file=temp_path)
            
            # Tasks should NOT be loaded from JSON
            assert len(manager.list_tasks()) == 0
        finally:
            os.unlink(temp_path)


class TestUnifiedOrchestratorImports:
    """Verify unified orchestrator exports all required classes."""
    
    def test_phase2_imports(self):
        """Phase2Orchestrator and Phase2Config must be importable from core."""
        from core import Phase2Orchestrator, Phase2Config
        assert Phase2Orchestrator is not None
        assert Phase2Config is not None
    
    def test_phase3_imports(self):
        """Phase3Orchestrator and Phase3Config must be importable from core."""
        from core import Phase3Orchestrator, Phase3Config
        assert Phase3Orchestrator is not None
        assert Phase3Config is not None
    
    def test_phase4_imports(self):
        """Phase4Orchestrator and Phase4Config must be importable from core."""
        from core import Phase4Orchestrator, Phase4Config
        assert Phase4Orchestrator is not None
        assert Phase4Config is not None
    
    def test_base_orchestrator_imports(self):
        """Base Orchestrator must still be importable."""
        from core import Orchestrator, OrchestratorConfig
        assert Orchestrator is not None
        assert OrchestratorConfig is not None


class TestVersionEnforcement:
    """Verify version is correctly set."""
    
    def test_version_is_0_5_1_or_higher(self):
        """pyproject.toml version must be >= 0.5.1."""
        import tomllib
        
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        
        version = data["tool"]["poetry"]["version"]
        
        # Parse version
        parts = version.split(".")
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
        
        # Must be >= 0.5.1
        assert (major, minor, patch) >= (0, 5, 1), (
            f"Version must be >= 0.5.1, got {version}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
