# Architecture Elevation Plan — 7/10 → 9.5+/10

**Source:** `architecture_audit_report.md`
**Target score:** ≥9.5/10
**Current deductions:** −1 (65 ignore_imports) −1 (45KB orchestrator) −0.5 (fat service layer) −0.5 (no container boundaries) = **7/10**
**Strategy:** Recover 2.5+ points across 4 strategies; all must succeed.

---

## Strategy A: Zero-Ignore Contracts (recover ~1.0 point)

**Goal:** Reduce `ignore_imports` from 65 to ≤10 across all 4 import-linter contracts.

**Why this recovers the point:** The −1 deduction was for "chronic boundary leakage." At ≤10 exceptions, the contracts reflect reality — the remaining handful are truly justified composition-root wiring. The rubric's "all layers correctly separated" criterion is demonstrably met.

### Sprints

| Sprint | Goal | Deliverable |
|--------|------|-------------|
| **A1** | Audit all 65 ignores; classify them | `tasks/plans/ignore_imports_taxonomy.md` — category, justification, migration path per entry |
| **A2** | Extract 8 missing ports | 8 new `application/ports/` files + 8 adapter method extractions + 8 ignores removed |
| **A3** | Extract 8 more ports | Same pattern |
| **A4** | Extract 8 more ports | Same pattern |
| **A5** | Extract final 8 ports | Total: 32 new ports extracted, 32 ignores removed |
| **A6** | DI composition-root exemption | Create `weebot/interfaces/_composition_root.py` — a dedicated module where DI wiring is allowed to import everything. Add import-linter contract exemptions scoped to this file ONLY. Remaining 23 interface-level ignores moved here. |
| **A7** | Infrastructure adapter cleanup | 10 infra-level ignores resolved by port extraction + DI-lazy-load pattern |
| **A8** | Final contract enforcement | Run `lint-imports` with ≤10 total ignores. Add fitness test `test_ignore_imports_under_10` to CI. |

**Acceptance:** `lint-imports --config .importlinter` reports ≤10 total `ignore_imports` entries across all contracts. New fitness test passes in CI.

---

## Strategy B: Orchestrator Decomposition (recover ~1.0 point)

**Goal:** Reduce `PlanActFlow` from 45 KB / 965 lines to ≤15 KB / ≤300 lines. Decompose into 4–5 focused collaborators.

**Why this recovers the point:** The −1 deduction was for the orchestrator being a single-point coupling hub. Decomposition into focused coordinators with narrow interfaces satisfies the "patterns consistent" rubric criterion and eliminates the God Module anti-pattern.

### Sprints

| Sprint | Goal | Deliverable |
|--------|------|-------------|
| **B1** | Extract `FlowStateMachine` | New file: `weebot/application/flows/flow_state_machine.py`. Pure state-transition logic — which state follows which, under which conditions. ≤150 lines. PlanActFlow delegates state transitions to this. |
| **B2** | Extract `ToolExecutionOrchestrator` | New file: `weebot/application/flows/tool_execution_orchestrator.py`. Handles tool dispatch, parallel execution, result validation, and tool-result caching. ≤200 lines. PlanActFlow delegates tool calls to this. |
| **B3** | Extract `StepPipelineOrchestrator` | New file: `weebot/application/flows/step_pipeline_orchestrator.py`. Coordinates per-step flow: critique → pre-mortem → execute → review → verify. ≤200 lines. |
| **B4** | Extract `EventPublisher` | New file: `weebot/application/flows/event_publisher.py`. Single responsibility: publish typed agent events (EventBusPort + state_repo persistence). ≤100 lines. |
| **B5** | Extract `AgentSessionManager` | New file: `weebot/application/flows/agent_session_manager.py`. Session lifecycle: create, resume, checkpoint, complete. ≤150 lines. |
| **B6** | Thin PlanActFlow to coordinator | PlanActFlow becomes a thin coordinator (≤300 lines) that wires the 5 collaborators and delegates. Its `__init__` takes 5–7 parameters (the new collaborators) instead of 20+ raw services. |
| **B7** | Update DI container | Replace `build_plan_act_flow()` with helper that constructs the 5 collaborators and injects them into PlanActFlow. |
| **B8** | Regression suite | Run full test suite. Add fitness test `test_plan_act_flow_under_300_lines`. |

**Acceptance:** `PlanActFlow` ≤300 lines. 5 new collaborator files, each ≤200 lines. All existing tests pass. No behavioral regression in agent execution.

---

## Strategy C: Service Layer Consolidation (recover ~0.5 point)

**Goal:** Reduce `application/services/` from 100+ files to ~75. Eliminate dead code, merge near-duplicates, relocate domain logic to `domain/services/`.

**Why this recovers the point:** The −0.5 deduction was for a fat service layer. A 25% reduction with clear rationale (not arbitrary deletion) demonstrates intentional service decomposition.

### Sprints

| Sprint | Goal | Deliverable |
|--------|------|-------------|
| **C1** | Dead-code audit | Scan all 100+ services for callers. Flag any with 0 callers. Produce report. |
| **C2** | Remove dead services | Delete services with 0 callers and no CI reference. Estimated: 5–10 files. |
| **C3** | Merge near-duplicate services | Identify services with Jaccard similarity >0.7 in their import graph. Merge. Estimated: 3–5 merges, 6–10 files collapsed into 3–5. |
| **C4** | Relocate domain logic | Move services whose sole dependency is `domain/models/` + stdlib to `domain/services/`. Estimated: 5–8 files. |
| **C5** | Extract domain-service ports | For each relocated domain service, add a `domain_service_port.py`. Infrastructure adapters depend on the port, not the service. |
| **C6** | Consolidation verification | Run full test suite + import-linter. Service count ≤75 confirmed by `find weebot/application/services/ -name "*.py" | wc -l`. |

**Acceptance:** `application/services/` file count ≤75. `domain/services/` has 5+ new files. No imports from `application/` into relocated domain services. All tests pass.

---

## Strategy D: Container Boundaries (recover ~0.5 point)

**Goal:** Add Docker + docker-compose with correct service boundaries. Decouple SQLite migration from startup.

**Why this recovers the point:** The −0.5 deduction was for "no deployment/container boundary evidence." Adding Docker manifests demonstrates the architecture supports deployment-isolated boundaries and satisfies the "testable, scalable" rubric criteria.

### Sprints

| Sprint | Goal | Deliverable |
|--------|------|-------------|
| **D1** | Dockerfile for weebot | `Dockerfile` — multi-stage, Python 3.12, copies only `weebot/`, install requirements, entrypoint. |
| **D2** | Dockerfile for weebot-ui | `weebot-ui/Dockerfile` — Next.js 14 build, lightweight runner. |
| **D3** | docker-compose.yml | `docker-compose.yml` — 3 services: `weebot-api` (FastAPI + MCP), `weebot-ui` (Next.js), `weebot-scheduler` (cron jobs). Volumes for SQLite + logs. |
| **D4** | Database migration decoupling | `docker-entrypoint.sh` — runs `alembic upgrade head` before starting the app. Separate from runtime code. |
| **D5** | CI integration | Add `docker compose build` and `docker compose up -d && sleep 5 && curl localhost:8000/health && docker compose down` to `.github/workflows/architecture.yml`. |

**Acceptance:** `docker compose up` starts the full stack. `curl localhost:8000/health` returns 200. CI validates the Docker build is not broken.

---

## Strategy E: Core Cross-Cutting Contract (protect recovered points)

**Goal:** Add import-linter contract forbidding `weebot/core/` from importing `weebot/application/`.

**Sprints:**

| Sprint | Goal | Deliverable |
|--------|------|-------------|
| **E1** | Add contract to `.importlinter` | `contract:core-no-app` — `forbidden_modules = weebot.application.*` for `source_modules = weebot.core`. |
| **E2** | Fix any violations | If contract flags violations, refactor to use ports or config-level constants. |
| **E3** | Add fitness test | `test_core_no_application_imports` — verifies the contract is present and passing. |

**Acceptance:** New contract KEPT in `lint-imports`. Fitness test passes.

---

## Strategy F: Middleware Actualization (cleanup)

**Goal:** Implement the declared middleware pattern with ≥3 composable middleware classes.

**Sprints:**

| Sprint | Goal | Deliverable |
|--------|------|-------------|
| **F1** | Implement `ToolDispatchMiddleware` | Middleware that routes tool calls through `ToolExecutionOrchestrator`. Implements `before_request` / `after_tool_call`. |
| **F2** | Implement `TrajectoryMonitorMiddleware` | Middleware that records trajectory data. Implements `after_tool_call`. |
| **F3** | Implement `StepValidationMiddleware` | Middleware that validates step results. Implements `after_response`. |
| **F4** | Wire into agent pipeline | Add middleware stack to `PlanActFlow` initialization. Remove scattered ad-hoc calls to trajectory/validation logic. |

**Acceptance:** `weebot/application/middleware/` contains 3+ middleware class files with lifecycle methods. Agent pipeline uses `for mw in self.middleware: await mw.before_request(...)` pattern.

---

## Strategy G: Architecture Decision Records (documentation)

**Goal:** Write ADRs for the 5 most impactful architectural decisions.

**Sprints:**

| Sprint | Goal | Deliverable |
|--------|------|-------------|
| **G1** | ADR-001: Clean Hexagonal Architecture | Why Clean Arch over MVC/pipeline. Accepted tradeoffs. |
| **G2** | ADR-002: CQRS + Event Sourcing | Why separate command/query. Event store design. |
| **G3** | ADR-003: SQLite as primary store | Rationale. Migration path to PostgreSQL. Scaling limits. |
| **G4** | ADR-004: Import-Linter enforcement | Why mechanical enforcement over code review. Contract design. |
| **G5** | ADR-005: Multi-model cascade | Why 4-tier cascade over single-model. Cost vs quality tradeoffs. |

**Acceptance:** 5 ADR files in `docs/adr/`. Linked from `REASONIX.md`.

---

## Strategy H: Tool Registration Simplification (reliability)

**Goal:** Single registration point for new tools. Current: 4-step dance.

**Sprints:**

| Sprint | Goal | Deliverable |
|--------|------|-------------|
| **H1** | Autodiscovery by directory scan | `RoleBasedToolRegistry` automatically discovers `BaseTool` subclasses in `weebot/tools/` via `pkgutil.iter_modules`. Eliminates manual `_TOOL_MODULE_NAMES` list. |
| **H2** | Role mapping via class attribute | Each tool declares `allowed_roles: list[str]` on its class. Registry reads this instead of maintaining a separate `DEFAULT_ROLE_MAPPINGS`. |
| **H3** | DI auto-import | `_create_sub_agent_factory` discovers tools from registry instead of hardcoded import list. |

**Acceptance:** Adding a new tool requires: (1) Create the file, (2) Set `name`, `allowed_roles` on the class. No other files touched. Fitness test verifies this property.

---

## Score Recovery Map

| Strategy | Points Recovered | Cumulative Score |
|----------|-----------------|-----------------|
| Baseline | — | **7.0** |
| A: Zero-Ignore Contracts | +1.0 | 8.0 |
| B: Orchestrator Decomposition | +1.0 | 9.0 |
| C: Service Layer Consolidation | +0.5 | 9.5 |
| D: Container Boundaries | +0.5 | 10.0 |
| E–H: Hardening | Protect recovered points | ≥9.5 sustained |

**Target: 9.5+ after Strategies A–D complete. Strategies E–H ensure the score doesn't regress.**

---

## Execution Sequence

```
Sprint  Week 1   Week 2   Week 3   Week 4   Week 5   Week 6   Week 7   Week 8
A1–A2   ████████
A3–A4            ████████
A5–A6                     ████████
A7–A8                              ████████
B1–B3   ████████
B4–B6            ████████
B7–B8                     ████████
C1–C2            ████████
C3–C4                     ████████
C5–C6                              ████████
D1–D3   ████████
D4–D5            ████████
E1–E3                                     ████████
F1–F4                                              ████████
G1–G5                                     ████████
H1–H3                                              ████████
```

**Total:** 8 weeks, ~2 sprints. Strategies A–D are parallelizable. Strategies E–H run after A–D.

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| **B (Orchestrator decomposition) breaks agent loop** | MEDIUM | CRITICAL — all flows stop | Extensive regression suite (Strategy B8). Deploy to staging first. Rollback = revert to monolithic PlanActFlow. |
| **A (Port extraction) introduces import cycles** | LOW | HIGH — import-linter would catch it | Each port extraction is a separate PR. Run import-linter per PR. |
| **C (Service deletion) removes code needed at runtime via dynamic dispatch** | LOW | MEDIUM | Use `search_content` + `find_in_code` before deletion. Dead-code check must be 100% accurate. |
| **D (Docker) doesn't work on Windows dev machines** | MEDIUM | LOW | Dockerfile is additive — doesn't replace local Python setup. Dev workflow unchanged. |
| **H (Autodiscovery) changes tool loading order** | LOW | LOW | Registry ordering isn't relied upon by any code path. |
