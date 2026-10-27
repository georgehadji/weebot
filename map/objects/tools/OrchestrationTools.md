---
type: object
name: Orchestration tools
code: DebateTool, SwarmTool, DispatchAgentsTool, WorkflowOrchestratorTool, MixtureOfAgentsTool, ReasonerTool, BerbTool, TerminateTool, AskHumanTool, TodoWriteTool, ScheduleTool, PersistentMemoryTool, AuditTool, HeuristicRouter
cluster: tools
universe: live
status: verified
verified: 2026-10-27
commit: 3223b7f2
---

# Orchestration tools

The tools that spawn sub-agent flows, call an LLM themselves, call an outside reasoning service, or steer the agent loop (stop, ask, track, schedule, remember, audit). They are ordinary `BaseTool`s; what sets them apart is the collaborators they need and who wires them.

## Why this shape
A sub-agent tool cannot build a flow itself without importing the composition root, so it takes a `flow_factory` callable and an `llm` port in its constructor and stores them as private attributes (`weebot/tools/dispatch_agents.py:93-103`, `weebot/tools/debate.py:97-100`). The registry decides per name which collaborator to pass (`weebot/application/services/tool_registry.py:456-497`); a tool built without one stays in the collection and returns an error result when called (`debate.py:103-104`, `swarm.py:95-100`, `dispatch_agents.py:108-112`, `workflow_orchestrator.py:113-118`, `mixture_of_agents.py:115-120`).

## Shape

| Tool name | Class, file:line | flow_factory | LLM port | state repo / other | Roles (`DEFAULT_ROLE_MAPPINGS`) |
|---|---|---|---|---|---|
| `debate` | `DebateTool` `weebot/tools/debate.py:71` | yes, passed to an inner `DispatchAgentsTool` (`:121-124`) | yes, reconciler `chat` (`:142-157`) | none | researcher, admin, webhook |
| `swarm` | `SwarmTool` `weebot/tools/swarm.py:30` | yes (`:140-145`) | yes, checked non-None (`:95-96`); the `GoalAgent` / `SynthesizerAgent` calls arrive as `decompose` / `synthesize` callables (`:80-81, 86-88, 107, 156`) | optional `swarm_bus`, else a new `SwarmEventBus` (`:121-126`) | researcher, admin, webhook |
| `dispatch_parallel_tasks` | `DispatchAgentsTool` `weebot/tools/dispatch_agents.py:27` | yes, one flow per task (`:125-130`) | no | `state_repo`, accepted and stored, never read (`:91, 102`) | admin, webhook |
| `workflow_orchestrator` | `WorkflowOrchestratorTool` `weebot/tools/workflow_orchestrator.py:29` | yes, one flow per DAG node (`:150-151`) | no | `state_repo`, accepted and stored, never read (`:105, 110`) | admin, webhook |
| `mixture_of_agents` | `MixtureOfAgentsTool` `weebot/tools/mixture_of_agents.py:55` | no | yes, field `llm_port` (`:105`) | none | admin, webhook |
| `reasoner` | `ReasonerTool` `weebot/tools/reasoner.py:18` | no | no (HTTP to `REASONER_API_URL`, default `http://localhost:8003`, then CLI in `REASONER_DIR`, `:125-129, 166-263`) | `set_config(ToolConfig)` (`:29`) | researcher, analyst, admin, webhook |
| `berb` | `BerbTool` `weebot/tools/berb.py:21` | no | no (CLI in `BERB_DIR` first, then HTTP `BERB_API_URL` default `:8004`, `:66-70, 87-141`) | `set_config(ToolConfig)` (`:32`) | researcher, analyst, admin, webhook |
| `terminate` | `TerminateTool` `weebot/tools/control.py:11` | no | no | none | admin only |
| `ask_human` | `AskHumanTool` `weebot/tools/control.py:38` | no | no | returns `data={"awaiting_human": True}` for the executor to pause (`:59-65`) | admin, webhook |
| `todo_write` | `TodoWriteTool` `weebot/tools/todo_tool.py:22` | no | no | optional `event_bus` (`:59-63`) | admin, webhook |
| `schedule` | `ScheduleTool` `weebot/tools/schedule_tool.py:24` | no | no | module singleton `SchedulingManager` (`:12-21`) | automation, admin, webhook |
| `persistent_memory` | `PersistentMemoryTool` `weebot/tools/persistent_memory.py:40` | no | no | `memory` required, `state_repo` optional for salience (`:89-117`) | admin, webhook |
| `audit_session` | `AuditTool` `weebot/tools/audit_tool.py:17` | no | no | `service: AuditPort` required (`:43-50`) | admin, webhook |
| (not a tool) | `HeuristicRouter` `weebot/tools/heuristic_router.py:17` | - | - | static keyword scoring | not a `BaseTool`; its only caller, the legacy `RecursiveWeebotAgent`, was retired in plan 3.5 |

Role lists: `weebot/application/services/tool_registry.py:27-185`.

Wiring, read from source:
- Registry branches (`weebot/application/services/tool_registry.py`): `_llm_port_tools = {"browser_navigator", "mixture_of_agents"}` gets `llm_port=` only when one was passed (`:457, 479-480`); `swarm` gets `llm`, `flow_factory` and the `decompose` / `synthesize` callables of `GoalAgent(llm_port)` / `SynthesizerAgent(llm_port)`, so the tool imports no agent (`:483-493`, plan 3.3); `debate` gets `llm=llm_port, flow_factory=flow_factory`, both possibly None (`:459, 494-495`); `{"dispatch_parallel_tasks", "workflow_orchestrator"}` get `flow_factory, state_repo` (`:461, 496-497`). `persistent_memory` and `audit_session` come from `wiring()["collaborators"]` and are skipped when their collaborator does not resolve (`:473-478, 507-517`; `application/di/_factories.py:480-522`).
- Output trust: `swarm`, `dispatch_parallel_tasks`, `workflow_orchestrator` and `debate` are `EXTERNAL` (sub-agents with tools may have browsed; moved from `LOCAL` on 2026-10-24, `weebot/tools/swarm.py:36`, `weebot/tools/dispatch_agents.py:40`, `weebot/tools/workflow_orchestrator.py:44`, `weebot/tools/debate.py:76`); the other ten are `LOCAL`. The rules are in `weebot/core/trust_boundary.py:58-90`.
- `flow_factory` is never in the registry's `wiring()` (it supplies `state_repo`, `browser_factory`, `rerank`, `tool_config`, `collaborators`, `_factories.py:513-522`; read at `application/services/tool_registry.py:446-452`). Only callers that pass it get working sub-agent tools: `application/di/_agent_tools.py:46-53`, `application/di/__init__.py:514-522` and `:651-661`, and `interfaces/factories.py:306-314` via `_get_flow_factory` (`:225-259`), which returns None when `llm_port` is None (`:230-231`).
- `_get_flow_factory` builds sub-flows with `tools=None` and the shared event bus (`factories.py:260-279`); `_agent_tools.py` builds them with the `admin` tool set and `event_bus=None` (`_agent_tools.py:49-64`).
- `ScheduleTool` refuses inside a cron job (`schedule_tool.py:110-121`). A `command` job is accepted (`:129-145`) but `SchedulingManager` raises `NotImplementedError` when it runs (`weebot/scheduling/scheduler.py:457-462`).

Consequences (read from source, not run):
- `build_tools` fills a missing `llm_port` from the shared container (`interfaces/factories.py:299-304`), so the web session router (`interfaces/web/routers/sessions.py:341`), the webhook router (`interfaces/web/routers/webhook.py:128`) and the gateways (e.g. `interfaces/gateways/discord.py:188`), which pass none, still get a flow factory; the CLI runner passes its own (`interfaces/cli/agent_runner.py:93-95`). The sub-agent tools stay dead but listed only when the container resolves no `LLMPort`, `StateRepositoryPort` or `EventBusPort` (`interfaces/factories.py:254-265`). MCP scoping rebuilds the collection with `llm_port` but no `flow_factory` (`application/flows/mcp_scope.py:84-86`), so `dispatch_parallel_tasks` and `workflow_orchestrator` fail and `debate`'s inner dispatcher returns an error after the scoped rebuild.
- Fixed 2026-10-23 (F49): `dispatch_parallel_tasks` and `workflow_orchestrator` no longer call a `save_sync` that never existed inside `except Exception: pass`. The sub-agent flow saves its own session through the flow factory's `state_repo` (`dispatch_agents.py:192`, `workflow_orchestrator.py:232`).
- `workflow_orchestrator` makes a new `asyncio.Semaphore(max_parallel)` inside each task call (`workflow_orchestrator.py:147`), so it limits nothing; the real cap is `max_parallel_agents` (`:171`).
- `swarm` collects `bus_insights` from the swarm bus (`swarm.py:150-154`) and never passes them to the synthesizer (`:156`).
- `todo_write` says its items stream to the UI (`todo_tool.py:28-33`), but nothing constructs `TodoWriteTool` with an `event_bus` (no `TodoWriteTool(` call in `weebot/` or `cli/`), so the registry's bare `tool_cls()` (`application/services/tool_registry.py:508-509`) always gets `_event_bus=None`.
- `reasoner` and `berb` start a Python subprocess with `asyncio.create_subprocess_exec` directly (`reasoner.py:229-235`, `berb.py:102-108`), outside the shell guard chain; neither bounds `communicate()` with a timeout. `berb` logs the full CLI command including the topic (`berb.py:99`), `reasoner` the problem text (`reasoner.py:226`).
- `mixture_of_agents` takes `reference_models` and `aggregator_model` from the model's arguments (`mixture_of_agents.py:107-124`); the cost cascade is not involved.

## Connected to
- **Built by** `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`) through the callers above, and `build_tools` in `weebot/interfaces/factories.py:286`.
- **Spawn** `PlanActFlow` sub-sessions (`dispatch_agents.py:125-130, 180-190`, `workflow_orchestrator.py:150-151, 220-234`); `swarm` is handed `application/agents/goal_agent.py` and `synthesizer_agent.py` methods by the registry (`:483-493`); `workflow_orchestrator` wraps the `WorkflowOrchestrator` engine (`workflow_orchestrator.py:170-177`).
- **Looks like but is not:** `SubAgentFactory` / `HyperAgentFlow` (`application/di/__init__.py:641-700`), the other multi-agent path; `PersonaRouter` (card `tools/Personas.md`); `HeuristicRouter`, whose only caller, the legacy `RecursiveWeebotAgent`, was retired in plan 3.5.

## If you change this
**Hits:** every caller that builds sub-agent tools (above), webhook and gateway tool sets, tests `tests/unit/tools/test_dispatch_agents.py`, `tests/unit/test_workflow_orchestrator.py`, `tests/unit/application/test_flow_construction_wiring.py`, `tests/unit/test_reasoner_tool.py`, `tests/unit/test_berb_tool.py`, `tests/unit/fixes/test_f15_tool_dirs_unset.py`, `tests/unit/tools/test_control.py`, `tests/unit/test_scheduler.py`, `tests/unit/test_persistent_memory.py`, `tests/unit/test_memory_metadata_repo.py`, `tests/unit/fixes/test_w55_tool_wiring.py`, `tests/unit/fixes/test_w53_tool_registry_collaborators.py`, `tests/unit/test_di_registries_are_wired.py`, `tests/unit/tools/test_heuristic_router.py`, `tests/unit/tools/test_swarm_injected_agents.py`. No test imports `DebateTool` or `MixtureOfAgentsTool`.
**Does not hit:** the shell guard set (none of these names is in `GUARDED_TOOLS`; `mixture_of_agents` is wrapped anyway because it matches the outbound patterns, `weebot/config/settings.py:435`); the planner/executor LLM roles.

## Surfaces
The agent's tool list for the roles above; `ask_human` pauses reach the user through the executor; `schedule` jobs reach the scheduler DB.

## See
`weebot/tools/dispatch_agents.py`
