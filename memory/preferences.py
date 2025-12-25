"""
User Preferences
----------------
Key-value store for user preferences.
Manual updates only - no auto-learning.

Rules:
- No inference
- No auto-learning
- Explicit updates only
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging
import yaml


@dataclass
class UserPreferences:
    """
    User preference storage.
    
    Examples:
    - Default browser
    - Preferred voice
    - Timezone
    - Volume level
    """
    
    preferences: Dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a preference value."""
        return self.preferences.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a preference value (explicit update only)."""
        self.preferences[key] = value
        self.updated_at = datetime.now()
    
    def remove(self, key: str) -> bool:
        """Remove a preference. Returns True if existed."""
        if key in self.preferences:
            del self.preferences[key]
            self.updated_at = datetime.now()
            return True
        return False
    
    def has(self, key: str) -> bool:
        """Check if a preference exists."""
        return key in self.preferences
    
    def keys(self) -> List[str]:
        """Get all preference keys."""
        return list(self.preferences.keys())
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "preferences": self.preferences.copy(),
            "updated_at": self.updated_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "UserPreferences":
        """Create from dictionary."""
        prefs = cls(preferences=data.get("preferences", {}))
        if "updated_at" in data:
            prefs.updated_at = datetime.fromisoformat(data["updated_at"])
        return prefs


class PreferenceStore:
    """
    Persistent preference storage.
    
    Stores preferences to disk in YAML format.
    All updates are explicit - no auto-learning.
    """
    
    # Default preferences
    DEFAULTS: Dict[str, Any] = {
        "language": "en",
        "timezone": "local",
        "default_browser": "default",
        "volume_default": 50,
        "confidence_threshold": 0.6,
        "max_results": 5,
    }
    
    def __init__(self, store_path: Optional[str] = None):
        self._path = Path(store_path) if store_path else Path("preferences.yaml")
        self._preferences = UserPreferences()
        self._logger = logging.getLogger("jarvis.memory.preferences")
        
        # Load existing preferences
        self._load()
    
    def _load(self) -> None:
        """Load preferences from disk."""
        if self._path.exists():
            try:
                with open(self._path, 'r') as f:
                    data = yaml.safe_load(f)
                    if data:
                        self._preferences = UserPreferences.from_dict(data)
                        self._logger.info(f"Loaded {len(self._preferences.preferences)} preferences")
            except Exception as e:
                self._logger.error(f"Failed to load preferences: {e}")
        
        # Apply defaults for missing keys
        for key, value in self.DEFAULTS.items():
            if not self._preferences.has(key):
                self._preferences.preferences[key] = value
    
    def _save(self) -> None:
        """Save preferences to disk."""
        try:
            with open(self._path, 'w') as f:
                yaml.dump(self._preferences.to_dict(), f, default_flow_style=False)
            self._logger.debug("Preferences saved")
        except Exception as e:
            self._logger.error(f"Failed to save preferences: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a preference value."""
        value = self._preferences.get(key)
        if value is None:
            value = self.DEFAULTS.get(key, default)
        return value
    
    def set(self, key: str, value: Any, save: bool = True) -> None:
        """
        Set a preference value.
        
        This is the ONLY way to update preferences.
        No auto-learning, no inference.
        """
        self._preferences.set(key, value)
        self._logger.info(f"Preference updated: {key} = {value}")
        
        if save:
            self._save()
    
    def remove(self, key: str, save: bool = True) -> bool:
        """Remove a preference."""
        result = self._preferences.remove(key)
        if result and save:
            self._save()
        return result
    
    def reset(self, key: str) -> None:
        """Reset a preference to default."""
        if key in self.DEFAULTS:
            self.set(key, self.DEFAULTS[key])
        else:
            self.remove(key)
    
    def reset_all(self) -> None:
        """Reset all preferences to defaults."""
        self._preferences = UserPreferences(preferences=self.DEFAULTS.copy())
        self._save()
        self._logger.info("All preferences reset to defaults")
    
    def list_all(self) -> Dict[str, Any]:
        """List all current preferences."""
        return self._preferences.preferences.copy()
    
    @property
    def preferences(self) -> UserPreferences:
        """Get the preferences object."""
        return self._preferences


def test_preferences() -> None:
    """Test preference storage."""
    import tempfile
    import os
    
    print("Testing Preference Store...")
    
    # Use temp file
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        temp_path = f.name
    
    try:
        store = PreferenceStore(temp_path)
        
        # Test defaults
        assert store.get("language") == "en"
        print("✓ Default values work")
        
        # Test set
        store.set("custom_key", "custom_value")
        assert store.get("custom_key") == "custom_value"
        print("✓ Set/get works")
        
        # Test persistence
        store2 = PreferenceStore(temp_path)
        assert store2.get("custom_key") == "custom_value"
        print("✓ Persistence works")
        
        # Test remove
        store.remove("custom_key")
        assert store.get("custom_key") is None
        print("✓ Remove works")
        
        # Test reset
        store.set("language", "fr")
        store.reset("language")
        assert store.get("language") == "en"
        print("✓ Reset works")
        
        print("\nAll tests passed!")
        
    finally:
        os.unlink(temp_path)


if __name__ == "__main__":
    test_preferences()
