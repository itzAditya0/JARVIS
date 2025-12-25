# JARVIS v1.0.0 — Identity & Guarantees

## What JARVIS Is

> **A forensic-grade, trust-first personal AI assistant with explicit governance, accountability, and reliability guarantees.**

JARVIS is a voice-driven tool orchestration system designed for users who require verifiable behavior, not just convenient automation.

---

## Who Should Use JARVIS

- Users who need **explainable AI decisions**
- Developers building **trust-critical automation**
- Organizations requiring **audit trails** for AI actions
- Anyone who asks: *"Can I prove what this AI did?"*

---

## Who Should NOT Use JARVIS

- Users seeking the fastest possible execution (governance has overhead)
- Projects where "move fast and break things" is acceptable
- Automation that requires silent, invisible operation
- Use cases where accountability is an afterthought

---

## The Guarantees

### Governance (v0.6.0+)
| Invariant | Guarantee |
|-----------|-----------|
| G1 | No tool executes without explicit grant |
| G2 | Revoked grants block execution immediately |
| G3 | Certain operations always require confirmation |
| G4 | All authority decisions are logged |

### Accountability (v0.7.0+)
| Invariant | Guarantee |
|-----------|-----------|
| A1 | All audit entries are HMAC-chained |
| A2 | turn_id is required for execution |
| A3 | Tamper-evident logging (not tamper-proof) |
| A4 | Deterministic serialization for hashes |

### Reliability (v0.8.0+)
| Invariant | Guarantee |
|-----------|-----------|
| R1 | Circuit breakers scoped per tool name |
| R2 | Failure budget enforced per turn |
| R3 | All exceptions classified before planner |
| R4 | Dependency-aware degradation aborts |
| R5 | Health monitoring is passive only |

### Stability (v0.9.0+)
| Invariant | Guarantee |
|-----------|-----------|
| C1 | Unknown config keys are errors |
| V1 | Breaking changes require MAJOR version |

---

## What v1.0 Means

This is not a feature milestone. This is a **promise**.

As of v1.0.0:
- The public API is **frozen**
- The invariants are **binding**
- Every change is classified as **patch, feature, or breaking**
- The system's identity is **declared and non-negotiable**

---

## The Trust Model

### What JARVIS Trusts
- The operating system boundary
- The HMAC key remains secret
- The user provides valid grants

### What JARVIS Does NOT Trust
- LLM outputs (validated, not trusted)
- Tool execution (sandboxed, not assumed safe)
- Network responses (classified as failures, not data)

---

## Recommended Post-v1.0 Behavior

### For Users
- Treat JARVIS decisions as auditable
- Review audit logs for disputed actions
- Grant permissions explicitly, not broadly

### For Developers
- Do not modify invariants without MAJOR bump
- Do not add "helpful" silent behaviors
- Test breaking changes against contract tests

---

## Philosophy (Locked)

> **JARVIS prioritizes correctness, traceability, and user authority over speed, autonomy, or convenience.**

---

## Final Statement

JARVIS v1.0.0 is complete.

Not because it does everything, but because it does what it promises — and nothing more.

> *"An AI assistant you can audit, correct, and trust."*
