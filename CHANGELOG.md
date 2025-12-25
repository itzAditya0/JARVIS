# Changelog

All notable changes to JARVIS will be documented in this file.

## [1.0.0] - 2025-12-25

### Identity Declaration

> **A forensic-grade, trust-first personal AI assistant with explicit governance, accountability, and reliability guarantees.**

This is not a feature release. This is a **promise**.

### Added
- `IDENTITY.md` — System identity and guarantees
- Configuration semantic freeze in `API.md`

### Guarantees (Binding)
- **Governance** (v0.6.0+): No tool executes without explicit grant
- **Accountability** (v0.7.0+): All actions are HMAC-chained and auditable
- **Reliability** (v0.8.0+): Predictable failure containment
- **Stability** (v0.9.0+): Breaking changes require MAJOR version

### What v1.0 Means
- The public API is frozen
- The invariants are binding
- Every change is classified as patch, feature, or breaking
- The system's identity is declared and non-negotiable

## [0.9.0] - 2025-12-25

### Added
- **Contract Documentation**
  - `INVARIANTS.md` — System guarantees by version
  - `API.md` — Public API surface with stability status
  - `VERSIONING.md` — Semantic versioning policy
- **Contract Tests** (`tests/test_contracts.py`)
  - API surface verification
  - Export existence tests

### Changed
- All `datetime.utcnow()` replaced with `datetime.now(timezone.utc)`
- Test isolation: subprocess `open` commands are mocked

### Fixed
- Deprecation warnings for timezone-naive datetime objects

### Policy
- **Unknown configuration keys are now errors**
- Public API is frozen; breaking changes require MAJOR version bump

## [0.8.0] - 2025-12-25

### Added
- **Circuit Breakers** (`core/circuit_breaker.py`)
  - State machine: CLOSED → OPEN → HALF_OPEN → CLOSED
  - Per-tool-name scope
  - Configurable thresholds and recovery timeout
- **Failure Isolation** (`core/degradation.py`)
  - `FailureBudget` per turn (max failures, consecutive limits)
  - Dependency-aware abort detection
  - `classify_exception()` for exception → JARVISError conversion
- **Graceful Degradation** (`core/degradation.py`)
  - Policy-driven strategies (FAIL_FAST, RETRY, SKIP, etc.)
  - Default policies by permission level
- **Health Monitoring** (`infra/health.py`)
  - Component health tracking (HEALTHY, DEGRADED, UNHEALTHY)
  - Error rate and latency metrics
  - Passive observability only

### Changed
- All exceptions converted to classified `JARVISError` before returning to planner

### Security
- Failure budget prevents runaway execution
- Circuit breakers prevent cascading failures

## [0.7.0] - 2025-12-25

### Added
- **Immutable Audit Log** (`infra/audit.py`) - HMAC-chained audit trail
  - Append-only enforcement (no UPDATE/DELETE in code)
  - Canonical JSON serialization for determinism
  - `verify_chain()` for tamper detection
  - `export_for_review()` for external audit
  - Attack simulation tests (middle entry deletion)
- **Audit Event Logging**
  - `TOOL_EXECUTE` events in executor (success/timeout/error)
  - `AUTHORITY_CHECK` events in authority

### Changed
- `turn_id` now propagated through all audit events
- Executor and authority log to immutable audit trail

### Security
- **Trust Boundary**: Tamper-evident assuming HMAC key is secret
- Key loaded from `JARVIS_AUDIT_KEY` env var, never in database

## [0.6.0] - 2025-12-25

### Added
- **Tool Authority System** - Centralized permission grants for tool execution
  - `PermissionGrant` with expiry and one-time support
  - YAML-configurable default grants
  - All decisions logged with `turn_id`
- **Confirmation Gates** - User confirmation required for WRITE/EXECUTE/NETWORK
  - `PendingConfirmation` workflow
  - Callback-based and deferred confirmation
  - Session grants after approval
- **Memory Governance** - Policy enforcement for memory storage
  - Static regex redaction for sensitive patterns (deterministic, auditable)
  - Hard retention limits (max_turns, max_age_days)
  - User deletion commands: "forget everything", "forget conversation"

### Changed
- `ToolExecutor` now uses `ToolAuthority` for permission checks
- All governance decisions include `turn_id` for auditability

## [0.5.1] - 2025-12-25

### Changed
- **Enforced single orchestrator path** - Deleted `orchestrator_v2.py`, `orchestrator_v3.py`, `orchestrator_v4.py`. All phases now in `orchestrator_unified.py`.
- **Removed JSON persistence from runtime** - `EventManager` no longer saves tasks to JSON. Use `DatabaseManager` instead.
- **Completed turn_id propagation** - Logging infrastructure ready for full traceability.

### Fixed
- Startup enforcement now hard-fails if legacy orchestrator files exist.

## [0.5.0] - 2025-12-24

### Added
- Centralized logging system (`infra/logging.py`) with turn_id context.
- SQLite database manager (`infra/database.py`) with schema versioning.
- Comprehensive test suite (36 tests).

### Changed
- Version bump to 0.5.0 for stability milestone.

## [0.4.0] - 2025-12-16

### Added
- Phase 4 multimodal capabilities (screenshot, camera, scheduling).
- Gemini API integration.
