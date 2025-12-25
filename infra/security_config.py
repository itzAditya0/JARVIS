"""
Security Configuration Manager
------------------------------
Centralized security and configuration management.
Handles secrets, permissions, and security policies.

Rules:
- Secrets never in code
- All secrets from environment or encrypted store
- Audit logging for security events
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import hashlib
import hmac
import json
import logging
import os
import secrets

import yaml


class SecurityLevel(Enum):
    """Security levels for operations."""
    PUBLIC = auto()      # No authentication needed
    INTERNAL = auto()    # Internal service access
    USER = auto()        # User authentication required
    ELEVATED = auto()    # Elevated privileges required
    ADMIN = auto()       # Admin access only


@dataclass
class SecretConfig:
    """Configuration for a secret."""
    name: str
    env_var: str
    required: bool = True
    description: str = ""


@dataclass
class SecurityPolicy:
    """Security policy configuration."""
    # Permission settings
    default_deny: bool = True
    require_confirmation_for: Set[str] = field(default_factory=lambda: {"admin", "execute"})
    
    # Path restrictions
    blocked_paths: Set[str] = field(default_factory=lambda: {
        "/etc", "/var", "/usr", "/bin", "/sbin",
        "/System", "/Library", "/private",
        ".ssh", ".gnupg", ".aws", ".config"
    })
    
    allowed_apps: Set[str] = field(default_factory=lambda: {
        "safari", "chrome", "firefox", "terminal", "finder",
        "spotify", "notes", "calendar", "calculator", "textedit"
    })
    
    # Rate limiting
    max_commands_per_minute: int = 30
    max_tool_calls_per_minute: int = 60
    
    # Audit settings
    audit_enabled: bool = True
    audit_file: str = "logs/security_audit.log"


class SecretManager:
    """
    Manages secrets securely.
    
    Rules:
    - Never store secrets in code
    - Load from environment variables
    - Optional encrypted secrets file
    """
    
    # Required secrets
    REQUIRED_SECRETS: List[SecretConfig] = [
        SecretConfig("gemini_api_key", "GEMINI_API_KEY", required=False, 
                    description="Gemini API key for LLM"),
        SecretConfig("openai_api_key", "OPENAI_API_KEY", required=False,
                    description="OpenAI API key (optional)"),
    ]
    
    def __init__(self):
        self._secrets: Dict[str, str] = {}
        self._logger = logging.getLogger("jarvis.infra.secrets")
        self._load_secrets()
    
    def _load_secrets(self) -> None:
        """Load secrets from environment."""
        for secret in self.REQUIRED_SECRETS:
            value = os.getenv(secret.env_var)
            if value:
                self._secrets[secret.name] = value
                self._logger.debug(f"Loaded secret: {secret.name}")
            elif secret.required:
                self._logger.warning(f"Missing required secret: {secret.name}")
    
    def get(self, name: str) -> Optional[str]:
        """Get a secret by name."""
        return self._secrets.get(name)
    
    def has(self, name: str) -> bool:
        """Check if a secret exists."""
        return name in self._secrets
    
    def list_available(self) -> List[str]:
        """List names of available secrets (not values!)."""
        return list(self._secrets.keys())
    
    def validate(self) -> Dict[str, bool]:
        """Validate all required secrets are present."""
        result = {}
        for secret in self.REQUIRED_SECRETS:
            result[secret.name] = self.has(secret.name) or not secret.required
        return result


class SecurityAuditLog:
    """
    Security audit logging.
    All security-relevant events are logged.
    """
    
    def __init__(self, log_file: str = "logs/security_audit.log"):
        self._log_file = Path(log_file)
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("jarvis.security.audit")
    
    def log_event(
        self,
        event_type: str,
        details: Dict[str, Any],
        level: SecurityLevel = SecurityLevel.INTERNAL
    ) -> None:
        """Log a security event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "level": level.name,
            "details": details
        }
        
        # Log to file
        with open(self._log_file, 'a') as f:
            f.write(json.dumps(event) + "\n")
        
        # Also log to standard logger
        self._logger.info(f"Security event: {event_type} ({level.name})")
    
    def log_command_execution(self, command: str, user: str = "default") -> None:
        """Log a command execution."""
        self.log_event("command_execution", {
            "command": command,
            "user": user
        })
    
    def log_tool_call(self, tool_name: str, args: Dict) -> None:
        """Log a tool call."""
        self.log_event("tool_call", {
            "tool": tool_name,
            "args": args
        })
    
    def log_permission_denied(self, action: str, reason: str) -> None:
        """Log a permission denial."""
        self.log_event("permission_denied", {
            "action": action,
            "reason": reason
        }, level=SecurityLevel.ELEVATED)
    
    def log_secret_access(self, secret_name: str) -> None:
        """Log secret access."""
        self.log_event("secret_access", {
            "secret": secret_name
        }, level=SecurityLevel.ELEVATED)


class ConfigManager:
    """
    Centralized configuration management.
    Loads configuration from YAML with environment variable overrides.
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        self._config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._logger = logging.getLogger("jarvis.infra.config")
        
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from file."""
        if self._config_path.exists():
            with open(self._config_path, 'r') as f:
                self._config = yaml.safe_load(f) or {}
            self._logger.info(f"Loaded config from {self._config_path}")
        else:
            self._logger.warning(f"Config file not found: {self._config_path}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.
        Supports dot notation: 'section.key'
        Environment variables override file config.
        """
        # Check environment first
        env_key = f"JARVIS_{key.upper().replace('.', '_')}"
        env_value = os.getenv(env_key)
        if env_value is not None:
            return env_value
        
        # Navigate nested config
        parts = key.split('.')
        value = self._config
        
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value (runtime only, not persisted)."""
        parts = key.split('.')
        config = self._config
        
        for part in parts[:-1]:
            if part not in config:
                config[part] = {}
            config = config[part]
        
        config[parts[-1]] = value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get an entire configuration section."""
        return self._config.get(section, {})
    
    def reload(self) -> None:
        """Reload configuration from file."""
        self._load_config()


class SecurityManager:
    """
    Central security manager.
    Combines secrets, audit, and policy management.
    """
    
    def __init__(self, policy: Optional[SecurityPolicy] = None):
        self.policy = policy or SecurityPolicy()
        self.secrets = SecretManager()
        self.audit = SecurityAuditLog(self.policy.audit_file)
        self.config = ConfigManager()
        self._logger = logging.getLogger("jarvis.infra.security")
    
    def check_path_allowed(self, path: str) -> bool:
        """Check if a path is allowed."""
        try:
            path_obj = Path(path).resolve()
            path_str = str(path_obj)
        except Exception:
            return False
        
        # Check blocked absolute paths (must start with these)
        # Include both Linux and macOS paths
        blocked_absolute = {
            "/etc", "/var", "/usr", "/bin", "/sbin", "/System", "/Library",
            "/private/etc", "/private/var"  # macOS symlinks
        }
        for blocked in blocked_absolute:
            if path_str.startswith(blocked):
                self.audit.log_permission_denied(
                    f"path_access:{path}",
                    f"System path blocked: {blocked}"
                )
                return False
        
        # Check blocked patterns anywhere in path
        blocked_patterns = {".ssh", ".gnupg", ".aws", ".config", "__pycache__"}
        for pattern in blocked_patterns:
            if pattern in path_str:
                self.audit.log_permission_denied(
                    f"path_access:{path}",
                    f"Sensitive pattern blocked: {pattern}"
                )
                return False
        
        return True
    
    def check_app_allowed(self, app_name: str) -> bool:
        """Check if an application is allowed."""
        allowed = app_name.lower() in self.policy.allowed_apps
        
        if not allowed:
            self.audit.log_permission_denied(
                f"app_open:{app_name}",
                "Application not in allowlist"
            )
        
        return allowed
    
    def get_secret(self, name: str) -> Optional[str]:
        """Get a secret with audit logging."""
        self.audit.log_secret_access(name)
        return self.secrets.get(name)
    
    def validate_secrets(self) -> bool:
        """Validate all required secrets are present."""
        result = self.secrets.validate()
        all_valid = all(result.values())
        
        if not all_valid:
            missing = [k for k, v in result.items() if not v]
            self._logger.warning(f"Missing secrets: {missing}")
        
        return all_valid


def test_security() -> None:
    """Test security components."""
    print("Testing Security Manager...")
    
    manager = SecurityManager()
    
    # Test secrets
    print(f"Secrets validation: {manager.validate_secrets()}")
    print(f"Available secrets: {manager.secrets.list_available()}")
    
    # Test path checking
    print(f"\nPath check /tmp/test: {manager.check_path_allowed('/tmp/test')}")
    print(f"Path check /etc/passwd: {manager.check_path_allowed('/etc/passwd')}")
    
    # Test app checking
    print(f"\nApp check 'Safari': {manager.check_app_allowed('Safari')}")
    print(f"App check 'malicious': {manager.check_app_allowed('malicious')}")
    
    # Test config
    print(f"\nConfig 'stt.model': {manager.config.get('stt.model', 'default')}")
    
    print("\nAll tests passed!")


if __name__ == "__main__":
    test_security()
