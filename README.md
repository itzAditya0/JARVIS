# JARVIS v1.0

> **A forensic-grade, trust-first personal AI assistant with explicit governance, accountability, and reliability guarantees.**

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

---

## Philosophy

> **JARVIS prioritizes correctness, traceability, and user authority over speed, autonomy, or convenience.**

---

## Features

### Core Capabilities

| Feature | Description |
|---------|-------------|
| 🎤 **Voice Control** | Push-to-talk with Faster-Whisper STT |
| 🧠 **Smart Planning** | Gemini LLM with automatic mock fallback |
| 💾 **Memory** | Conversation history and user preferences |
| 📸 **Multimodal** | Screenshot capture and camera input |
| ⏰ **Automation** | Event-driven task scheduling |

### Governance (v0.6.0+)

| Feature | Description |
|---------|-------------|
| 🔐 **Explicit Grants** | No tool executes without permission |
| ⏱️ **Grant Expiry** | Time-limited permissions with auto-revocation |
| ✅ **Confirmation Gates** | Dangerous operations require approval |
| 📋 **Decision Logging** | All authority decisions logged with turn_id |

### Accountability (v0.7.0+)

| Feature | Description |
|---------|-------------|
| 🔗 **HMAC-Chained Audit** | Tamper-evident append-only log |
| 🔍 **Full Traceability** | Every action linked to user request |
| ✓ **Chain Verification** | Cryptographic integrity checking |
| 📤 **Audit Export** | JSON bundles for external review |

### Reliability (v0.8.0+)

| Feature | Description |
|---------|-------------|
| ⚡ **Circuit Breakers** | Automatic failure isolation per tool |
| 📊 **Failure Budget** | Turn-level failure containment |
| 🔄 **Graceful Degradation** | Policy-driven fallback strategies |
| 💓 **Health Monitoring** | Component status tracking |

### Stability (v0.9.0+)

| Feature | Description |
|---------|-------------|
| 📜 **Frozen API** | Public API is stable |
| 📋 **Documented Invariants** | Binding system guarantees |
| 🔢 **Semantic Versioning** | Breaking changes require MAJOR bump |

---

## Quick Start

```bash
# Install dependencies
poetry install

# Run JARVIS
poetry run python main.py

# Test mode (text input)
poetry run python main.py --test
```

---

## Voice Commands

| Say This | Action |
|----------|--------|
| "What time is it?" | Get current time |
| "Take a screenshot" | Capture screen |
| "Take a photo" | Capture camera |
| "Open Spotify" | Launch application |
| "Search for Python tutorials" | Web search |
| "Schedule a reminder for 9am" | Create task |

---

## Available Tools

| Tool | Permission | Description |
|------|------------|-------------|
| `get_current_time` | READ | Current system time |
| `get_current_date` | READ | Current date |
| `web_search` | NETWORK | Search the web |
| `open_application` | EXECUTE | Launch apps |
| `set_volume` | EXECUTE | Adjust volume |
| `take_screenshot` | READ | Capture screen |
| `capture_camera` | READ | Capture from webcam |
| `schedule_task` | EXECUTE | Schedule tasks |

---

## Configuration

```bash
cp .env.example .env
```

```bash
GEMINI_API_KEY=your-api-key-here  # Optional - auto-fallback to mock
JARVIS_AUDIT_KEY=your-secret-key  # For HMAC audit chain
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| [IDENTITY.md](IDENTITY.md) | System identity and guarantees |
| [INVARIANTS.md](INVARIANTS.md) | Binding system invariants |
| [API.md](API.md) | Public API surface |
| [VERSIONING.md](VERSIONING.md) | Version policy |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

---

## Project Structure

```
JARVIS/
├── main.py              # Entry point
├── config.yaml          # Configuration
├── core/                # Orchestrator, errors, circuit breakers
├── tools/               # Tool registry, executor, authority
├── planner/             # LLM planner + mock fallback
├── memory/              # Conversation, preferences, governance
├── multimodal/          # Screenshot, camera, events
├── infra/               # Database, logging, audit, health
├── audio/               # Microphone capture
├── stt/                 # Speech-to-text
└── tests/               # 164 tests
```

---

## Security

- **Default Deny** — All tools require explicit grant
- **No Shell Access** — Commands use subprocess without `shell=True`
- **Allowlist Only** — Only predefined applications can be opened
- **HMAC Audit** — Tamper-evident logging of all actions
- **Failure Containment** — Circuit breakers prevent cascading failures

---

## Requirements

- Python 3.10+
- macOS (for system integrations)
- Optional: OpenCV for camera (`poetry add opencv-python`)
- Optional: Gemini API key (works without it)

---

## Running Tests

```bash
poetry run pytest tests/ -v
# 164 passed, 1 skipped
```

---

## License

MIT License — see [LICENSE](LICENSE)

---

> *"An AI assistant you can audit, correct, and trust."*
