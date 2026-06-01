# Core Module Classification

**Date:** 2026-06-01  
**Audit Reference:** Architecture Remediation Plan Phase 1.5  
**Target:** Classify all 28 modules in `weebot/core/` into their correct architectural layers.

---

## Classification

| Module | Target Layer | Rationale |
|--------|-------------|-----------|
| `agent_context.py` | **Application** | Agent orchestration context with state repository, event publishing, and shared data. Uses `StateRepositoryPort` and `EventPublisher` ports. |
| `agent.py` | **Application** | Base agent definition and lifecycle management. |
| `agent_factory.py` | **Application** | Factory for spawning agent instances with role-based tool sets. |
| `agent_profile.py` | **Application** | Agent profile configuration and metadata. |
| `tool_agent.py` | **Application** | Agent specialized for tool execution. |
| `workflow_orchestrator.py` | **Application** | Orchestrates multi-step workflows across agents. |
| `workflow_tracer.py` | **Application** | Traces workflow execution for debugging and replay. |
| `dependency_graph.py` | **Application** | Builds and resolves dependency graphs for task ordering. |
| `bash_guard.py` | **Infrastructure** | Bash command security guard with 4-tier risk assessment. Talks directly to OS interfaces (subprocess). |
| `safety.py` | **Infrastructure** | Safety policies and command validation rules. |
| `approval.py` | **Infrastructure** | User approval workflow for sensitive operations. |
| `approval_policy.py` | **Infrastructure** | Policy definitions controlling when approval is required. |
| `circuit_breaker.py` | **Infrastructure** | Circuit breaker for external service calls (LLMs, APIs). |
| `adaptive_concurrency.py` | **Infrastructure** | Adaptive concurrency management for LLM requests. |
| `memory_monitor.py` | **Infrastructure** | Memory usage monitoring and pressure handling. |
| `memory_dedup.py` | **Infrastructure** | Deduplication of event/response memory. |
| `model_cascade_config.py` | **Infrastructure** | Configuration for model cascade (fallback across models). |
| `model_cascade_integration.py` | **Infrastructure** | Integration layer connecting cascade to LLM adapters. |
| `openrouter_enhanced_cascade.py` | **Infrastructure** | OpenRouter-specific cascade implementation with cost optimization. |
| `openrouter_tools.py` | **Infrastructure** | OpenRouter tool calling integration. |
| `behavior_tracker.py` | **Infrastructure** | Tracks agent behavioral patterns over time. |
| `behavior_integration.py` | **Infrastructure** | Integrates behavior tracking with execution pipeline. |
| `behavior_reporting.py` | **Infrastructure** | Generates behavior reports for analysis. |
| `error_classifier.py` | **Infrastructure** | Classifies and categorizes errors for recovery. |
| `dashboard.py` | **Infrastructure** | Real-time monitoring dashboard data. |
| `alerting.py` | **Infrastructure** | Alert generation for operational issues. |
| `__init__.py` | — | Package init — no architectural significance. |

**Total:** 28 modules (1 init + 6 application + 21 infrastructure)

---

## Migration Plan (Phase 3 — Bucket C)

Files marked for **Application** will move to `weebot/application/core/` or remain with updated package references.

Files marked for **Infrastructure** will move to `weebot/infrastructure/core/` or be redistributed to existing infrastructure subpackages.

### Layer Definitions

| Layer | Depends On | Contains |
|-------|-----------|----------|
| **Domain** | Nothing | Business entities, ports (protocols), pure business logic |
| **Application** | Domain | Use cases, orchestration, CQRS handlers, flows, services |
| **Infrastructure** | Application + Domain | External adapters (LLM, DB, filesystem), security, observability |
| **Interfaces** | Application + Infrastructure | CLI, Web, MCP entry points |

### Dependency Rules

- **Application** modules may import from **Domain** only (no infrastructure imports at module level)
- **Infrastructure** modules may import from **Application** and **Domain**
- `core/` is a transitional location — modules classified here will be physically moved in Phase 3

---

## Verification

The classification above was produced by auditing each module's import graph:
- Modules importing `subprocess`, `sqlite3`, `aiohttp`, `httpx`, `psutil`, `asyncio.subprocess` → **Infrastructure**
- Modules importing `StateRepositoryPort`, `EventPublisher`, `LLMPort` → **Application** (via ports)
- Modules defining domain entities or protocols → **Domain**

```bash
# Verify no core module imports from an outer layer that its classification forbids
# (run after Phase 3 physical moves)
python -m importlinter --contracts weebot/core/contracts.ini
```
