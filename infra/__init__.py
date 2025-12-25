# Infrastructure module - Internal service bus, TTS, Logging, and Database
# FastAPI for internal communication, TTS for voice output

from .service_bus import ServiceBus, create_app
from .tts_engine import TTSEngine, TTSConfig, Voice, TTSBackend
from .security_config import (
    SecurityManager, SecretManager, ConfigManager,
    SecurityPolicy, SecurityLevel, SecurityAuditLog
)
from .logging import (
    get_logger, configure_logging, TurnContext,
    log_turn_end, get_turn_id, generate_turn_id
)
from .database import (
    DatabaseManager, Conversation, Turn, Memory, ScheduledTask,
    DatabaseError, SchemaMismatchError, MigrationFailedError,
    SCHEMA_VERSION
)

__all__ = [
    # Service Bus
    "ServiceBus",
    "create_app",
    # TTS
    "TTSEngine",
    "TTSConfig",
    "Voice",
    "TTSBackend",
    # Security
    "SecurityManager",
    "SecretManager", 
    "ConfigManager",
    "SecurityPolicy",
    "SecurityLevel",
    "SecurityAuditLog",
    # Logging (v0.5.0)
    "get_logger",
    "configure_logging",
    "TurnContext",
    "log_turn_end",
    "get_turn_id",
    "generate_turn_id",
    # Database (v0.5.0)
    "DatabaseManager",
    "Conversation",
    "Turn",
    "Memory",
    "ScheduledTask",
    "DatabaseError",
    "SchemaMismatchError",
    "MigrationFailedError",
    "SCHEMA_VERSION",
]

