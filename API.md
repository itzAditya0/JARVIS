# JARVIS Public API

> **Contract**: Symbols marked STABLE will not change without a major version bump.  
> Symbols marked INTERNAL have no stability guarantees.

---

## Stable API Surface

### core.errors

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `JARVISError` | dataclass | STABLE | v0.5.0 |
| `ErrorCategory` | Enum | STABLE | v0.5.0 |
| `RetryPolicy` | class | STABLE | v0.5.0 |
| `ErrorHandler` | class | STABLE | v0.5.0 |
| `create_tool_error()` | function | STABLE | v0.5.0 |
| `create_validation_error()` | function | STABLE | v0.5.0 |
| `create_llm_error()` | function | STABLE | v0.5.0 |
| `create_permission_error()` | function | STABLE | v0.5.0 |

---

### core.circuit_breaker

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `CircuitBreaker` | dataclass | STABLE | v0.8.0 |
| `CircuitState` | Enum | STABLE | v0.8.0 |
| `CircuitOpenError` | Exception | STABLE | v0.8.0 |
| `CircuitBreakerRegistry` | class | STABLE | v0.8.0 |
| `get_circuit_breaker()` | function | STABLE | v0.8.0 |
| `get_circuit_registry()` | function | STABLE | v0.8.0 |

---

### core.degradation

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `DegradationStrategy` | Enum | STABLE | v0.8.0 |
| `DegradationPolicy` | dataclass | STABLE | v0.8.0 |
| `FailureBudget` | dataclass | STABLE | v0.8.0 |
| `DegradationManager` | class | STABLE | v0.8.0 |
| `classify_exception()` | function | STABLE | v0.8.0 |
| `get_degradation_manager()` | function | STABLE | v0.8.0 |

---

### tools.authority

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `ToolAuthority` | class | STABLE | v0.6.0 |
| `PermissionGrant` | dataclass | STABLE | v0.6.0 |
| `AuthorityDecision` | dataclass | STABLE | v0.6.0 |
| `GrantStatus` | Enum | STABLE | v0.6.0 |

---

### tools.executor

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `ToolExecutor` | class | STABLE | v0.5.0 |
| `ExecutionResult` | dataclass | STABLE | v0.5.0 |
| `ExecutionStatus` | Enum | STABLE | v0.5.0 |
| `ExecutionContext` | dataclass | STABLE | v0.5.0 |
| `PendingConfirmation` | dataclass | STABLE | v0.6.0 |

---

### tools.registry

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `Tool` | dataclass | STABLE | v0.5.0 |
| `ToolSchema` | dataclass | STABLE | v0.5.0 |
| `ToolParameter` | dataclass | STABLE | v0.5.0 |
| `ToolRegistry` | class | STABLE | v0.5.0 |
| `PermissionLevel` | Enum | STABLE | v0.5.0 |

---

### infra.audit

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `AuditLog` | class | STABLE | v0.7.0 |
| `AuditEntry` | dataclass | STABLE | v0.7.0 |
| `EventType` | Enum | STABLE | v0.7.0 |
| `Actor` | Enum | STABLE | v0.7.0 |
| `VerifyResult` | dataclass | STABLE | v0.7.0 |
| `get_audit_log()` | function | STABLE | v0.7.0 |
| `audit_event()` | function | STABLE | v0.7.0 |

---

### infra.health

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `HealthMonitor` | class | STABLE | v0.8.0 |
| `ComponentHealth` | dataclass | STABLE | v0.8.0 |
| `HealthStatus` | Enum | STABLE | v0.8.0 |
| `get_health_monitor()` | function | STABLE | v0.8.0 |

---

### memory.governance

| Export | Type | Status | Since |
|--------|------|--------|-------|
| `MemoryGovernor` | class | STABLE | v0.6.0 |
| `MemoryPolicy` | dataclass | STABLE | v0.6.0 |

---

## Semantic Guarantees

### What MUST Always Happen

1. **turn_id is required** for tool execution (TypeError if None)
2. **Audit entries are chained** with HMAC
3. **Circuit breakers respect state machine** transitions
4. **Failure budget aborts turn** when exceeded
5. **Exceptions are classified** before returning to planner

### What MAY Change (Minor Version)

1. New error categories
2. New event types
3. New health metrics
4. Additional helper functions

### What Is Explicitly Undefined

1. Circuit breaker state after restart (resets to CLOSED)
2. Audit log behavior if HMAC key changes mid-session
3. Health thresholds (currently 10%/50%)

### Configuration Stability (v0.9.0+)

> **As of v0.9.0, unknown or undocumented configuration keys result in a hard error.**

- No silent ignoring of typos
- No forward-compatibility guessing
- Configuration schema follows same versioning rules as API

---

## Internal APIs (No Stability Guarantee)

The following are internal and may change without notice:

- `core.orchestrator_unified` internals
- `planner.*` internals
- `multimodal.*` internals
- Any symbol prefixed with `_`
- Test fixtures and helpers
