---
type: object
name: Orchestration tools
code: DebateTool, SwarmTool, DispatchAgentsTool, WorkflowOrchestratorTool, MixtureOfAgentsTool, ReasonerTool, BerbTool, TerminateTool, AskHumanTool, TodoWriteTool, ScheduleTool, PersistentMemoryTool, AuditTool, HeuristicRouter
cluster: tools
universe: live
status: stale
stale_reason: 2026-10-24 remediation moved code these citations point at (tool registry, trust boundary, flow builder, DI); re-verify against source
verified: 2026-10-24
commit: d4ffb555
---

# Orchestration tools

The tools that spawn sub-agent flows, call an LLM themselves, call an outside reasoning service, or steer the agent loop (stop, ask, track, schedule, remember, audit). They are ordinary `BaseTool`s; what sets them apart is the collaborators they need and who wires them.

## Why this shape
A sub-agent tool cannot build a flow itself without importing the composition root, so it takes a `flow_factory` callable and an `llm` port in its constructor and stores them as private attributes (`weebot/tools/dispatch_agents.py:88-98`, `weebot/tools/debate.py:92-95`). The registry decides per name which collaborator to pass (`weebot/tools/tool_registry.py:448-478`); a tool built without one stays in the collection and returns an error result when called (`debate.py:98-99`, `swarm.py:82-83`, `dispatch_agents.py:103-107`, `workflow_orchestrator.py:108-113`, `mixture_of_agents.py:112-117`).

## Shape

| Tool name | Class, file:line | flow_factory | LLM port | state repo / other | Roles (`DEFAULT_ROLE_MAPPINGS`) |
|---|---|---|---|---|---|
| `debate` | `DebateTool` `weebot/tools/debate.py:70` | yes, passed to an inner `DispatchAgentsTool` (`:116-119`) | yes, reconciler `chat` (`:138-152`) | none | researcher, admin, webhook |
| `swarm` | `SwarmTool` `weebot/tools/swarm.py:28` | yes (`:126-131`) | yes, `GoalAgent` and `SynthesizerAgent` (`:89-93, 144-147`) | optional `swarm_bus`, else a new `SwarmEventBus` (`:107-112`) | researcher, admin, webhook |
| `dispatch_parallel_tasks` | `DispatchAgentsTool` `weebot/tools/dispatch_agents.py:26` | yes, one flow per task (`:121-125`) | no | `state_repo` (`:86, 91-97`) | admin, webhook |
| `workflow_orchestrator` | `WorkflowOrchestratorTool` `weebot/tools/workflow_orchestrator.py:28` | yes, one flow per DAG node (`:145-146`) | no | `state_repo` (`:100, 227-233`) | admin, webhook |
| `mixture_of_agents` | `MixtureOfAgentsTool` `weebot/tools/mixture_of_agents.py:54` | no | yes, field `llm_port` (`:102`) | none | admin, webhook |
| `reasoner` | `ReasonerTool` `weebot/tools/reasoner.py:17` | no | no (HTTP to `REASONER_API_URL`, default `http://localhost:8003`, then CLI in `REASONER_DIR`, `:122-126, 164-259`) | `set_config(ToolConfig)` (`:26-28`) | researcher, analyst, admin, webhook |
| `berb` | `BerbTool` `weebot/tools/berb.py:20` | no | no (CLI in `BERB_DIR` first, then HTTP `BERB_API_URL` default `:8004`, `:63-138`) | `set_config(ToolConfig)` | researcher, analyst, admin, webhook |
| `terminate` | `TerminateTool` `weebot/tools/control.py:8` | no | no | none | admin only |
| `ask_human` | `AskHumanTool` `weebot/tools/control.py:33` | no | no | returns `data={"awaiting_human": True}` for the executor to pause (`:52-58`) | admin, webhook |
| `todo_write` | `TodoWriteTool` `weebot/tools/todo_tool.py:21` | no | no | optional `event_bus` (`:56-60`) | admin, webhook |
| `schedule` | `ScheduleTool` `weebot/tools/schedule_tool.py:23` | no | no | module singleton `SchedulingManager` (`:11-20`) | automation, admin, webhook |
| `persistent_memory` | `PersistentMemoryTool` `weebot/tools/persistent_memory.py:39` | no | no | `memory` required, `state_repo` optional for salience (`:86-114`) | admin, webhook |
| `audit_session` | `AuditTool` `weebot/tools/audit_tool.py:16` | no | no | `service: AuditPort` required (`:40-47`) | admin, webhook |
| (not a tool) | `HeuristicRouter` `weebot/tools/heuristic_router.py:17` | - | - | static keyword scoring | not a `BaseTool`; its only caller, the legacy `RecursiveWeebotAgent`, was retired in plan 3.5 |

Role lists: `weebot/tools/tool_registry.py:27-177`.

Wiring, read from source:
- Registry branches: `_llm_port_tools = {"browser_navigator", "mixture_of_agents"}` gets `llm_port=` only when one was passed (`tool_registry.py:449, 471-472`); `{"debate", "swarm"}` always get `llm=llm_port, flow_factory=flow_factory`, both possibly None (`:451, 475-476`); `{"dispatch_parallel_tasks", "workflow_orchestrator"}` get `flow_factory, state_repo` (`:453, 477-478`). `persistent_memory` and `audit_session` come from `wiring()["collaborators"]` and are skipped when their collaborator does not resolve (`:465-470`; `application/di/_factories.py:454-473`).
- `flow_factory` is never in the registry's `wiring()` (it supplies `state_repo`, `rerank`, `tool_config`, `collaborators`, `_factories.py:466-474`; read at `tool_registry.py:439-444`). Only callers that pass it get working sub-agent tools: `application/di/_agent_tools.py:46-53`, `application/di/__init__.py:492-500` and `:629-639`, and `interfaces/factories.py:368-376` via `_get_flow_factory` (`:311-345`), which returns None when `llm_port` is None (`:316-317`).
- `_get_flow_factory` builds sub-flows with `tools=None` and the shared event bus (`factories.py:329-341`); `_agent_tools.py` builds them with the `admin` tool set and `event_bus=None` (`_agent_tools.py:49-64`).
- `ScheduleTool` refuses inside a cron job (`schedule_tool.py:107-118`). A `command` job is accepted (`:126-142`) but `SchedulingManager` raises `NotImplementedError` when it runs (`weebot/scheduling/scheduler.py:457-462`).

Consequences (read from source, not run):
- Callers that pass no `llm_port` leave the sub-agent tools dead but listed: the web session router (`interfaces/web/routers/sessions.py:291`), the webhook router (`interfaces/web/routers/webhook.py:123-124`) and the gateways (e.g. `interfaces/gateways/discord.py:188`) call `build_tools(role=...)` with no `llm_port`; only the CLI runner passes one (`interfaces/cli/agent_runner.py:87-89`). MCP scoping rebuilds the collection with `llm_port` but no `flow_factory` (`application/flows/mcp_scope.py:84-86`), so `dispatch_parallel_tasks` and `workflow_orchestrator` fail and `debate`'s inner dispatcher returns an error after the scoped rebuild.
- Fixed 2026-10-23 (F49): `dispatch_parallel_tasks` and `workflow_orchestrator` no longer call a `save_sync` that never existed inside `except Exception: pass`. The sub-agent flow saves its own session through the flow factory's `state_repo` (`dispatch_agents.py:175-189`).
- `workflow_orchestrator` makes a new `asyncio.Semaphore(max_parallel)` inside each task call (`workflow_orchestrator.py:142`), so it limits nothing; the real cap is `max_parallel_agents` (`:165-166`).
- `swarm` collects `bus_insights` from the swarm bus (`swarm.py:138-142`) and never passes them to the synthesizer (`:145-147`).
- `todo_write` says its items stream to the UI (`todo_tool.py:25-30`), but nothing constructs `TodoWriteTool` with an `event_bus` (no `TodoWriteTool(` call in `weebot/` or `cli/`), so the registry's bare `tool_cls()` (`tool_registry.py:487-489`) always gets `_event_bus=None`.
- `reasoner` and `berb` start a Python subprocess with `asyncio.create_subprocess_exec` directly (`reasoner.py:226-232`, `berb.py:99-105`), outside the shell guard chain; neither bounds `communicate()` with a timeout. `berb` logs the full CLI command including the topic (`berb.py:96`), `reasoner` the problem text (`reasoner.py:223`).
- `mixture_of_agents` takes `reference_models` and `aggregator_model` from the model's arguments (`mixture_of_agents.py:104-120`); the cost cascade is not involved.

## Connected to
- **Built by** `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`) through the callers above, and `build_tools` in `weebot/interfaces/factories.py:348`.
- **Spawn** `PlanActFlow` sub-sessions (`dispatch_agents.py:175-185`, `workflow_orchestrator.py:215-225`); `swarm` uses `application/agents/goal_agent.py` and `synthesizer_agent.py`; `workflow_orchestrator` wraps the `WorkflowOrchestrator` engine (`workflow_orchestrator.py:165-172`).
- **Looks like but is not:** `SubAgentFactory` / `HyperAgentFlow` (`application/di/__init__.py:619-668`), the other multi-agent path; `PersonaRouter` (card `tools/Personas.md`); `HeuristicRouter`, whose only caller, the legacy `RecursiveWeebotAgent`, was retired in plan 3.5.

## If you change this
**Hits:** every caller that builds sub-agent tools (above), webhook and gateway tool sets, tests `tests/unit/tools/test_dispatch_agents.py`, `tests/unit/test_workflow_orchestrator.py`, `tests/unit/application/test_flow_construction_wiring.py`, `tests/unit/test_reasoner_tool.py`, `tests/unit/test_berb_tool.py`, `tests/unit/fixes/test_f15_tool_dirs_unset.py`, `tests/unit/tools/test_control.py`, `tests/unit/test_scheduler.py`, `tests/unit/test_persistent_memory.py`, `tests/unit/test_memory_metadata_repo.py`, `tests/unit/fixes/test_w55_tool_wiring.py`, `tests/unit/fixes/test_w53_tool_registry_collaborators.py`, `tests/unit/test_di_registries_are_wired.py`, `tests/unit/tools/test_heuristic_router.py`, `tests/unit/tools/test_swarm_injected_agents.py`. No test imports `DebateTool` or `MixtureOfAgentsTool`.
**Does not hit:** the guard chain (none of these names is in the shell `GUARDED_TOOLS`); the planner/executor LLM roles.

## Surfaces
The agent's tool list for the roles above; `ask_human` pauses reach the user through the executor; `schedule` jobs reach the scheduler DB.

## See
`weebot/tools/dispatch_agents.py`
