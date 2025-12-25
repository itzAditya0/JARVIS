# JARVIS System Invariants

> **Contract**: These invariants are guaranteed as of the stated version.  
> Violating these invariants is a bug, not a feature.

---

## Governance Invariants (v0.6.0+)

### G1: Explicit Grant Requirement
> **No tool executes without explicit grant.**

- Default grants are explicit, pre-approved grants loaded at startup
- There are no implicit permissions
- Unknown tools are denied by default

### G2: Immediate Revocation
> **Revoked or expired grants immediately block execution.**

- No grace period
- No "finish current operation" exceptions
- Mid-session revocation is effective immediately

### G3: Confirmation Gates
> **Certain permission levels always require user confirmation.**

- `WRITE`, `EXECUTE`, `NETWORK` require confirmation unless pre-granted
- Confirmation timeout results in denial, not retry
- No silent escalation

### G4: Decision Logging
> **All authority decisions are logged with turn_id.**

- Grants, denials, and confirmations are logged
- turn_id provides traceability
- Logs are observable

---

## Accountability Invariants (v0.7.0+)

### A1: HMAC Chain Integrity
> **All audit entries are HMAC-chained.**

- Each entry's hash depends on the previous entry
- Chain is append-only (no UPDATE, no DELETE in code)
- Any modification breaks the chain

### A2: turn_id Requirement
> **turn_id is required for all tool executions.**

- Execution without turn_id is forbidden (v0.9.0+: TypeError)
- turn_id links user request to all resulting actions
- Full traceability from input to outcome

### A3: Trust Boundary
> **The audit log is tamper-evident, not tamper-proof.**

- Assumes HMAC key is secret (OS/process boundary)
- Attacker with DB + key access can recompute chain
- This is documented, not hidden

### A4: Canonical Serialization
> **Audit entry hashes use deterministic serialization.**

- Fixed field order
- JSON with sorted keys
- Explicit UTF-8 encoding

---

## Reliability Invariants (v0.8.0+)

### R1: Circuit Breaker Scope
> **Circuit breakers are scoped per tool name.**

- One breaker per tool
- State: CLOSED → OPEN → HALF_OPEN → CLOSED
- Breaker state is in-memory (reset on restart)

### R2: Failure Budget
> **Failure budget is enforced per turn.**

- Max 3 failures per turn
- Max 2 consecutive failures
- Exceeding budget aborts the turn

### R3: Exception Classification
> **All exceptions are classified before returning to planner.**

- Raw exceptions never reach orchestrator context
- Every exception becomes a typed `JARVISError`
- Classification is deterministic

### R4: Dependency-Aware Abort
> **If a skipped tool is a dependency, the turn aborts.**

- No silent partial results
- Honest failure over misleading success
- User is informed of abort reason

### R5: Health Observability
> **Health monitoring is passive only.**

- No auto-disable based on health
- No auto-switch strategies
- Health is visibility, not control

---

## Configuration Invariants (v0.9.0+)

### C1: Strict Configuration
> **Unknown or undocumented configuration keys are errors.**

- No silent ignoring of typos
- No "forward compatibility" guessing
- Explicit is better than implicit

---

## Test Isolation Invariants (v0.8.0+)

### T1: Hermetic Tests
> **Tests do not cause external side effects.**

- `webbrowser.open()` is blocked
- `subprocess.run(["open", ...])` is mocked
- CI pipelines do not hang

---

## Versioning Invariants (v0.9.0+)

### V1: Semantic Versioning
> **Breaking changes require major version bump.**

- MAJOR: Breaking API or invariant change
- MINOR: New features (backward compatible)
- PATCH: Bug fixes only
