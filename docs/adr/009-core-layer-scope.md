# ADR-009: Core Layer Scope Definition

**Status:** Accepted  
**Date:** 2026-07-07  
**Deciders:** Architecture team  

## Context

`weebot/core/` contains 44 files spanning bash guards, approval policies,
circuit breakers, error classification, credential sanitization, agent
factories, and a dashboard.  No ADR has defined what constitutes a
"core" module vs an "infrastructure" module, leading to scope creep:
`core/safety.py` had a LangChain dependency, `core/agent.py` imports
ChatOpenAI, and `core/dashboard.py` reads the filesystem.

## Decision

**Core = stateless, pure-logic, no I/O, no framework dependencies.**

| Belongs in `weebot/core/` | Belongs in `infrastructure/` |
|---|---|
| Safety rules (bash_guard, egress_guard) | Security scanners that need filesystem access |
| Approval policies (approval_policy, approval) | LLM-based safety analysis (migrated from core/safety.py) |
| Error classification (error_classifier) | Observability adapters (prometheus, otel) |
| Circuit breakers (circuit_breaker) | Persistence adapters |
| Credential sanitization (pure function) | Browser/sandbox adapters |
| Secret redaction (pure function) | Network adapters (MCP client manager) |
| Gateway auth (pure function) | Notification adapters |
| Trust boundary (classification logic) | Dashboard (filesystem reads) |
| Model cascade config (data class) | Agent factory (DI orchestration) |

**Explicitly excluded from core:**

- Any `import langchain`, `import openai`, `import aiohttp`
- Any `open()`, `Path.read_text()`, `subprocess.run()`
- Any module that mutates global state at import time
- Any module whose primary purpose is I/O or framework integration

## Consequences

- `core/safety.py` decoupled from LangChain (Architecture 9 Plan Step 1.3).
- `core/agent.py` LangChain deps sunset alongside `agent_core_v2.py` (2027-03-01).
- `core/dashboard.py` migrated to `infrastructure/observability/dashboard.py`.
- New core modules must pass a "no-I/O, no-framework-dep" gate in code review.
- Import-linter contract `core-no-app` gains a companion `core-no-infra` contract.

## Compliance Checklist

For any file in `weebot/core/`, verify:

- [ ] Zero imports from `weebot.infrastructure.*`
- [ ] Zero imports from `langchain`, `openai`, `aiohttp`, `httpx`
- [ ] No file I/O (`open()`, `Path.read_text()`, `Path.write_text()`)
- [ ] No subprocess calls (`subprocess.run`, `subprocess.Popen`)
- [ ] No global state mutation at module level
- [ ] All external dependencies injected via constructor (ports)
