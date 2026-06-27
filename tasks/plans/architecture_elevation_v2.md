# Architecture Elevation Plan — 8/10 → 9.5+/10 (V2)

**Source:** `architecture_audit_report.md` (ARCH-AUDIT-V2)
**Current score:** 8/10
**Deductions:** −1 (52 `ignore_imports`) −1 (45KB PlanActFlow)
**Target:** ≥9.5

---

## Strategy A: Slash ignore_imports (52 → ≤10) — recover ~0.75 point

The 52 exceptions break down into 5 contract buckets. Each resolved entry
represents one fewer documented boundary violation.

### Bucket 1: tools-no-db (8 entries) — Target: 2

| # | Entry | Fix |
|---|-------|-----|
| 1 | `scheduler → sqlite3` | Scheduler receives `SchedulerConfigPort` with DB path in constructor |
| 2–8 | 7 tools → `application.di` | Extract `ToolConfigPort`. Tools receive config in constructor, DI container passes it |

### Bucket 2: infra-no-app-services (10 entries) — Target: 2

| # | Entry | Fix |
|---|-------|-----|
| 1–2 | `tool_discovery → tool_registry + base` | Already resolved: autodiscovery eliminated `tool_discovery.py` dependency. Remove entries from `.importlinter`. |
| 3 | `apify.actor_registry → apify_actor_tool` | Extract `ApifyCapabilityPort`. Registry depends on port. |
| 4 | `sub_agent_factory → models.tool_collection` | **Keep.** `ToolCollection` is a DTO, not a service. Legitimate exception. |
| 5 | `external_service_integration → tools.base` | Extract `CapabilityRoutingPort`. |
| 6 | `interface_customization → profile_manager` | Extract `ProfileReadPort`. |
| 7–8 | `mcp_tool_bridge + mcp_toolkit_adapter → tools.base` | Extract `MCPToolBasePort`. |
| 9 | `mcp_tool_bridge → mcp_tool_port` | **Already correct.** Remove ignore — it's a port import. |
| 10 | `sqlite_state_repo → commitment_extractor` | **Already fixed.** `commitment_extractor` moved to `domain/services/`. Remove ignore. |

### Bucket 3: interfaces-no-infra (27 entries) — Target: 4

| # | Category | Count | Fix |
|---|----------|-------|-----|
| 1–7 | Web routers → `application.di` | 7 | Create `interfaces/_composition_root.py`. All DI wiring lives here. One import-linter exemption scoped to this file. Remaining 6 entries removed. |
| 8–9 | Health router → `infrastructure.browser.*` | 2 | Extract `BrowserHealthPort`. Health router depends on port. |
| 10–11 | Routers → `application.services.*` | 2 | Extract `ModelSelectionPort`, `TaskRunnerPort`. |
| 12 | Webhook → `plan_act_flow` | 1 | Extract `FlowFactoryPort`. |
| 13–17 | `interfaces.factories → 5 targets` | 5 | Move factory to `_composition_root.py`. |
| 18–19 | `cli.agent_runner → 2 targets` | 2 | Extract `CLIRunnerPort`. |
| 20 | `ops_router → cqrs.mediator` | 1 | Extract `CommandDispatchPort`. |
| 21 | `web.main → scheduling.default_jobs` | 1 | Move to `_composition_root.py`. |
| 22–23 | `windows.* → 2 targets` | 2 | **Keep.** Platform-specific adapters. |
| 24 | `web.main → infrastructure.persistence.connection_pool` | 1 | Extract `ConnectionPoolPort`. |

### Bucket 4: core-no-app (5 entries) — Target: 1

| # | Entry | Fix |
|---|-------|-----|
| 1–2 | `core.agent → browser_tool + powershell_tool` | Move agent construction from core to `application/factories/` |
| 3–4 | `core.agent_factory → tools.base + tool_registry` | Same — move factory to application |
| 5 | `core.agent_factory → agent_core_v2` | Remove `agent_core_v2` shim entirely |

### Bucket 5: domain-purity (0 entries) — Target: 0

No changes needed. Domain layer is clean. [VERIFIED]

### Total: 52 → target ≤10

| Bucket | Start | Keep | Fix | Target |
|--------|-------|------|-----|--------|
| tools-no-db | 8 | 1 (scheduler) | 7 | 2 |
| infra-no-app | 10 | 1 (DTO) | 9 | 2 |
| interfaces-no-infra | 27 | 2 (Windows) | 25 | 4 |
| core-no-app | 5 | 1 (legacy shim) | 4 | 1 |
| **Total** | **52** | **5** | **47** | **≤10** |

---

## Strategy B: Orchestrator Decomposition (45KB → ≤15KB) — recover ~1.0 point

Split `PlanActFlow` into 5 focused collaborators, each ≤200 lines.

| # | New File | Lines | Responsibility |
|---|----------|-------|----------------|
| 1 | `application/flows/flow_state_machine.py` | ≤150 | Pure state-transition logic — which state follows which |
| 2 | `application/flows/tool_execution_orchestrator.py` | ≤200 | Tool dispatch, parallel execution, result validation, result caching |
| 3 | `application/flows/step_pipeline_orchestrator.py` | ≤200 | Per-step: critique → pre-mortem → execute → review → verify |
| 4 | `application/flows/event_publisher.py` | ≤100 | Publish typed agent events (EventBusPort + state_repo persistence) |
| 5 | `application/flows/agent_session_manager.py` | ≤150 | Session lifecycle: create, resume, checkpoint, complete |

**PlanActFlow becomes thin coordinator** (≤300 lines) that wires the 5
collaborators and delegates. Constructor takes 5–7 parameters instead of 20+.

### Extraction sequence

1. **EventPublisher** — easiest. One responsibility, well-isolated code in `_emit()`.
2. **AgentSessionManager** — self-contained. Session lifecycle methods are clearly bounded.
3. **FlowStateMachine** — pure logic. Extract state-transition conditions into a decision table.
4. **StepPipelineOrchestrator** — depends on 1, 2, 3 being available.
5. **ToolExecutionOrchestrator** — depends on 2, 3 being available.

---

## Execution Plan

| Week | Task |
|------|------|
| 1 | Strategy A: Bucket 5 (core-no-app), Bucket 2 cleanup (2 entries already resolved). Write `_composition_root.py`. |
| 2 | Strategy A: Bucket 1 (tools DI bypasses — extract ToolConfigPort). Bucket 2 (remaining 8 ports). |
| 3 | Strategy A: Bucket 3 (interfaces consolidation — 15+ ports + composition root). Final enforcement: ≤10 ignores. |
| 4 | Strategy B: Extract EventPublisher + AgentSessionManager. |
| 5 | Strategy B: Extract FlowStateMachine + StepPipelineOrchestrator. |
| 6 | Strategy B: Extract ToolExecutionOrchestrator + thin PlanActFlow. Regression suite. |

**Total: 6 weeks.**

---

## Score Recovery Map

| Strategy | Points | Cumulative Score |
|----------|--------|-----------------|
| Baseline | — | 8.0 |
| A: ignore_imports ≤10 | +0.75 | 8.75 |
| B: PlanActFlow ≤15KB | +1.0 | 9.75 |

---

## Verification Gates

After each strategy:
- `lint-imports --config .importlinter` — contracts must stay KEPT, count must decrease
- `pytest tests/unit/test_architecture_fitness.py` — 45/46 must remain passing
- `wc -l weebot/application/flows/plan_act_flow.py` — decreasing trend per sprint for B
- `grep -c ignore_imports .importlinter` — decreasing trend per sprint for A
