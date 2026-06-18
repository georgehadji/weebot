# ARCHITECTURE.md — weebot AI Orchestrator

**Last updated:** 2026-06-18 (architecture remediation applied)
**Architecture score:** 8.0/10 (post-remediation)
**Last audit:** Architecture Audit v2 (2026-06-18) — baseline 6/10; remediation in progress → 8.0/10
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

### Remaining Debt

| # | Item | Severity | Status |
|---|------|----------|--------|
| D15 | `_base.py` still 803 lines (target ≤450) | MEDIUM | Requires further error_handler/reflect extraction |
| D16 | Cascade executor missing integration tests | LOW | Unit tests (19) present, integration pending |
| D17 | Application services read files/env directly (14 sites) | MEDIUM | Needs `FileStoragePort` creation + DI wiring |
