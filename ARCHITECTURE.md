# ARCHITECTURE.md — weebot AI Orchestrator

**Last updated:** 2026-06-18 (architecture remediation applied)
**Architecture score:** 8.5/10 (post-remediation)
**Last audit:** Architecture Audit v3 (2026-06-18) — baseline 6/10; v1 remediation → 8.0/10; v2 remediation → 8.5/10
**Maturity:** Production
**Paradigm:** Clean Architecture (Hexagonal Ports & Adapters) + CQRS Mediator + State-Machine Flows

---

## Recent Changes (2026-06-07)


## Architecture Remediation Update (2026-06-18)

**Audit score:** 6/10 → **Estimated: 7.5-8.0/10** (post-remediation)
**Remediation plan:** ARCHITECTURE_REMEDIATION_PLAN.md
**ExecutorAgent:** 1,414 lines → 803 lines (−43%), 4 collaborators extracted

### Completed Changes

| Change | Files |
|--------|-------|
| ExecutorAgent extraction | `_cascade.py`, `_tool_executor.py`, `_context_compressor.py`, `_error_handler.py` |
| Port creation (SkillStorePort, TrajectoryRepositoryPort) | `ports/skill_store_port.py`, `ports/trajectory_repository_port.py` |
| Application→infrastructure leakage fix | 6 handlers/flows updated; `transfer_handler.py` DI-injected |
| Core layer boundary fix | `scan_for_injection` → `infrastructure/security/` |
| Mutable state fixes | `_TOOL_TIERS` accessors, `reset_all_buckets()`, `_reset_metrics_cache()` |
| Metrics bridge | `services/metrics_bridge.py`; 3 callers updated |
| CQRS handler split | `handlers.py` (779→321 lines) → 8 individual handler files |
| Deprecated port deletion | `capability_gate_port.py`, `truth_binding_port.py` |

### New Architecture Decision Records

**ADR-006:** Port Rationalization (2026-06-18) — Delete ports with <2 implementations and no planned polymorphism. 2 deprecated ports deleted. 27 single-impl ports retained as they have callers.

**ADR-007:** ExecutorAgent Extraction (2026-06-18) — Split 1,414-line god class into 5 focused units: orchestrator (`_base.py`, ~800 lines), cascade executor (295 lines), tool executor (198 lines), context compressor (149 lines), error handler (129 lines).

**ADR-008:** Port Rationalization v2 (2026-06-18) — ToolDiscoveryPort and TaskQueuePort deleted (zero non-TYPE_CHECKING runtime callers). Plan's original estimate of "39 deletable ports" corrected to 2 — remaining 30 single-impl ports all have DI registrations or runtime consumers and are retained with planned-polymorphism documentation.

**ADR-009:** FlowRouter Extraction (2026-06-18) — State-transition routing logic extracted from PlanActFlow.run() into FlowRouter.resolve_initial_state(). Routing decisions now testable in isolation. Session context mutations (flag clearing, misalignment recording) preserved via tuple return (FlowState, Session).

### v2 Completed Changes (2026-06-18)

| Change | Files | Impact |
|--------|-------|--------|
| FlowRouter extraction | `flows/flow_router.py`, `flows/plan_act_flow.py` | State routing testable in isolation |
| `query_handlers.py` split | 3 files (session/plan/active) | 445→avg 150 lines per file |
| `_handle_step_completion` extraction | `agents/executor/_base.py` | execute_step reduced ~40 lines |
| `reset_global_pool()` added | `infrastructure/browser/session_pool.py` | Test isolation for browser pool |
| Port cleanup v2 | `ToolDiscoveryPort`, `TaskQueuePort` deleted | 2 unused ABCs removed |
| Cascade integration tests | `tests/integration/test_cascade_integration.py` | 8 tests, env-var gated |
| Architecture fitness tests | `test_architecture_fitness.py` | 5 new tests (39 total) |

### Remaining Debt

| # | Item | Severity | Status |
|---|------|----------|--------|
| D15 | `plan_act_flow.py` imports 29 modules (target 20) | LOW | FlowRouter extraction done; further reduction needs DI refactoring |
| D16 | `_base.py` still 823 lines (target 620) | MEDIUM | `_handle_step_completion` extracted; preamble (~100 lines) still inline |
| D17 | Application services read files/env directly (14 sites) | LOW | `FileStoragePort` exists; migration deferred as config files are acceptable |
| D18 | Failure signature handler 310 lines (limit 350) | LOW | Near limit; split in next pass if growth continues |
