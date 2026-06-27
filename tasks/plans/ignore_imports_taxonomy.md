# ignore_imports Taxonomy — 52 Entries Across 4 Contracts

**Source:** `.importlinter`
**Count:** 9 (tools-no-db) + 10 (infra-no-app-services) + 28 (interfaces-no-infra) + 5 (core-no-app) = **52**
**Target:** ≤10 remaining after all sprints

---

## Contract 1: `tools-no-db` — 9 entries

**Target:** 0 entries (eliminate all tool-level DI bypasses)

| # | Entry | Category | Migration Path | Priority |
|---|-------|----------|----------------|----------|
| 1 | `scheduling.scheduler -> sqlite3` | **Legitimate exception** — scheduler needs its own cron-jobs DB | Create `SchedulerConfigPort` that provides DB connection string. Scheduler connects to port-configured DB, not direct sqlite3. | **A2** |
| 2 | `schedule_tool -> scheduling.scheduler` | **Legitimate invocation** — tool delegates to scheduler service | Create `SchedulerPort`. Schedule tool depends on port, scheduler implements port. | **A2** |
| 3 | `audit_tool -> application.di` | **Lazy DI bypass** — should receive dependencies via constructor | Extract `AuditServicePort`. Tool receives port in constructor (DI container injects it). | **A2** |
| 4 | `knowledge_tool -> application.di` | **Lazy DI bypass** | Same as #3 — extract `KnowledgeServicePort`. | **A2** |
| 5 | `persistent_memory -> application.di` | **Lazy DI bypass** | Extract `MemoryServicePort`. | **A3** |
| 6 | `tool_registry -> application.di` | **Lazy DI bypass** | ToolRegistry should receive its config via constructor. | **A3** |
| 7 | `video_ingest_tool -> application.di` | **Lazy DI bypass** | Extract `VideoIngestPort`. | **A3** |
| 8 | `voice_input_tool -> application.di` | **Lazy DI bypass** | Extract `VoiceInputPort`. | **A3** |
| 9 | `voice_output_tool -> application.di` | **Lazy DI bypass** | Extract `VoiceOutputPort`. | **A3** |

**Strategy:** Extract ServicePort interfaces → tools accept ports in constructor → DI container passes implementations → tools no longer call `Container.get()`.

---

## Contract 2: `infra-no-app-services` — 10 entries

**Target:** 2 entries (2 legitimate exceptions for well-documented MCP patterns)

| # | Entry | Category | Migration Path | Priority |
|---|-------|----------|----------------|----------|
| 10 | `tool_discovery -> tool_registry` | **Missed port** — discovery reads tool metadata | Create `ToolRegistryReadPort` (read-only interface). Discovery depends on port, not concrete registry. | **A4** |
| 11 | `tool_discovery -> tools.base` | **Missed port** — discovery reads `BaseTool` metadata | Inline capability metadata into `ToolRegistryReadPort`. Discovery doesn't import tools.base directly. | **A4** |
| 12 | `apify.actor_registry -> apify_actor_tool` | **Missed port** — registry wraps tool for actor discovery | Create `ApifyActorPort`. Registry depends on port. | **A4** |
| 13 | `sub_agent_factory -> models.tool_collection` | **Legitimate DTO import** — factory constructs ToolCollection | Accept: `ToolCollection` is a data class, not a service. This is a valid DTO import. | **Keep as exception** |
| 14 | `external_service_integration -> tools.base` | **Legitimate extension** — extends BaseTool | Migrate capability routing behind `ToolCapabilityPort`. | **A5** |
| 15 | `interface_customization -> profile_manager` | **Missed port** — infra reads profile settings | Create `ProfileReadPort`. | **A5** |
| 16 | `mcp_tool_bridge -> tools.base` | **Legitimate extension** — MCP extends BaseTool | Create `MCPToolBasePort`. Bridge depends on port, not tools.base. | **A5** |
| 17 | `mcp_toolkit_adapter -> tools.base` | **Legitimate extension** — same as #16 | Merge with #16 — single `MCPToolBasePort`. | **A5** |
| 18 | `mcp_tool_bridge -> mcp_tool_port` | **Already a port** — this is the correct pattern! | Keep — this is what the architecture should look like. | **Keep as model** |
| 19 | `sqlite_state_repo -> commitment_extractor` | **Leak** — persistence calls application service | Move commitment extraction to `CommitmentPort` in application layer. infra implements port, doesn't call service directly. | **A6** |

---

## Contract 3: `interfaces-no-infra` — 28 entries

**Target:** 8 entries (moved to single composition-root exemption in `_composition_root.py`)

| # | Entry | Category | Migration Path | Priority |
|---|-------|----------|----------------|----------|
| 20–26 | `web.routers.*` → `application.di` (7 entries) | **DI wiring** — routers resolve Dependencies per-request | Move to `interfaces/_composition_root.py` — exempt file. | **A6** |
| 27–28 | `web.routers.health` → `infrastructure.browser.*` (2 entries) | **Direct infra access** — health checks browser pool | Create `BrowserHealthPort`. Health router depends on port. | **A6** |
| 29–30 | `web.routers.health.models` → `application.services.model_selection` (2 entries) | **Legitimate service call** | Create `ModelSelectionPort`. | **A6** |
| 31 | `web.routers.sessions` → `task_runner` | **Legitimate service call** | Create `TaskRunnerPort`. | **A6** |
| 32 | `web.routers.webhook` → `plan_act_flow` | **Direct flow import** | Create `FlowFactoryPort`. Webhook calls port to create flows. | **A6** |
| 33–37 | `interfaces.factories` → 5 targets | **Composition root** — factory builds the full stack | Move factory to `_composition_root.py`. | **A6** |
| 38–39 | `cli.agent_runner` → 2 targets | **CLI composition root** | Move to `_composition_root.py` or extract `CLIRunnerPort`. | **A6** |
| 40 | `web.routers.ops_router` → `cqrs.mediator` | **Direct CQRS access** | Create `CommandDispatchPort`. | **A6** |
| 41 | `web.main` → `scheduling.default_jobs` | **Startup job registration** | Move to `_composition_root.py`. | **A6** |
| 42–43 | `windows.*` → 2 targets | **Platform-specific** — Windows adapters | Keep as platform-specific exceptions. | **Keep** |
| 44 | `web.main` → `infrastructure.persistence.connection_pool` | **Startup connection pooling** | Create `ConnectionPoolPort`. | **A6** |

---

## Contract 4: `core-no-app` — 5 entries (NEW)

**Target:** 3 entries (remove 2 via extraction)

| # | Entry | Category | Migration Path | Priority |
|---|-------|----------|----------------|----------|
| 45–46 | `core.agent` → `tools.browser_tool`, `tools.powershell_tool` | **Legacy agent config** | Core agent shouldn't import tools directly. Move agent construction to `application/factories/`. | **B5** |
| 47 | `core.agent_factory` → `tools.base` | **Legacy factory** | Same as above — move factory to application. | **B5** |
| 48 | `core.agent_factory` → `tools.tool_registry` | **Legacy registry access** | `agent_factory` should receive configured tools via DI. | **B5** |
| 49 | `core.agent_factory` → `agent_core_v2` | **Legacy shim** | Remove `agent_core_v2` entirely. | **A6** |

---

## Summary

| Type | Count | Keep | Extract Port | Move to _composition_root |
|------|-------|------|-------------|---------------------------|
| Lazy DI bypass (tools → di) | 7 | 0 | 7 | 0 |
| Legitimate exception (will keep) | 2 | 2 | 0 | 0 |
| Missed port (infra → app) | 8 | 0 | 8 | 0 |
| Composition root (interfaces → infra) | 25 | 2 (Windows) | 6 | 17 |
| Core legacy (core → tools/app) | 5 | 0 | 2 | 3 |
| **Total** | **52** | **4** | **23** | **20** |

**Strategy:** 23 new ports + 1 composition-root exempt file = 21 ignore_imports removed after full execution (target: ≤10, with the 4 legitimate exceptions + 6 not-yet-addressed).
