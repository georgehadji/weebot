---
type: object
name: CLI
code: cli (click group), AgentRunner, interfaces.factories
cluster: interfaces
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# CLI

The `python -m cli.main` click application: one root group `cli` (`cli/main.py:132-137`) plus command groups imported from `cli/commands/` and `weebot/interfaces/cli/`. Agent runs go through `AgentRunner` (`weebot/interfaces/cli/agent_runner.py:32`), which builds tools and flows with `create_flow` / `build_tools` in `weebot/interfaces/factories.py`.

## Why this shape
Each command group lives in its own module and is attached with `cli.add_command` at the bottom of `cli/main.py` (`:707-744`), so `cli/main.py` keeps only ops commands (init, doctor, health, costs, hooks, upgrades). Every entry point is meant to share one DI container per process: `shared_container()` (`weebot/interfaces/factories.py:71-87`), built lazily under a lock. The same factories module serves the web routers and the chat gateways, so the CLI and the server build flows the same way.

## Shape
Root commands in `cli/main.py`:

| Command | Line | What it does |
|---|---|---|
| `create`, `status`, `run`, `resume`, `checkpoint` | `:169-228` | print "deprecated, use flow"; nothing else |
| `list-projects` | `:177-195` | `state_repo.list_sessions()` from the shared container |
| `delete` | `:231-237` | prints "Deleted project" and deletes nothing (comment `:236`) |
| `export` | `:240-254` | dumps one session to JSON |
| `costs` | `:263-288` | `GetCostSummaryHandler` over a fresh `EventStore()` (`:257-260`) |
| `init`, `doctor`, `health` | `:303-510` | `init_project` / `run_doctor` from `weebot/interfaces/cli/support.py:52, 212`; `health` adds a model ping (`:455-458`) |
| `hooks init/install`, `check-updates`, `upgrade`, `implement` | `:513-623` | support helpers; `implement` only writes a plan JSON |
| `research init-experiment/validate-data/obsidian-sync` | `:292-696` | imports `research_modules`, `integrations.obsidian` |

Groups registered at `:707-744`:

| Group | Module | Wires |
|---|---|---|
| `flow` (run, resume, list, cancel, retry, undo, skillopt, export, search, decisions) | `cli/commands/flow.py:94-451` | `AgentRunner` with LLM from `ModelSelectionService`, state repo and `Mediator` from the shared container (`:107-122`) |
| `hyper` | `cli/commands/hyper.py:27` | shared container, `event_bus=container.get(EventBusPort)` (`:60`) |
| `skill`, `agents`, `profile`, `cron`, `companion`, `guard`, `analytics`, `soul`, `dream`, `mcp`, `gateway`, `cron-agent`, `auth`, `ponytail*` | `cli/commands/*.py` | see each module; `mcp` manages the MCP client config, not the MCP server |
| `benchmark`, `harness` | `cli/commands/harness.py:12, 140` | each builds its own `Container()` (`:55, 95, 254, 350`), not the shared one |
| `behavior` | `weebot/interfaces/cli/behavior_commands.py:17` | file-change ledger: watch, status, stop, report, trust, log, override, reflect, summary, reset, doctor |

`flow run` (`cli/commands/flow.py:100-156`): streams `runner.run_prompt`, and on each `WaitForUserEvent` reads an answer with `asyncio.to_thread(input)`; on EOF it leaves the session WAITING and prints the resume command (`:140-148`). `_run_async` (`:27-75`) installs `ConsoleApproval` when stdin is a TTY (`:44-55`), then drains background tasks, closes the MCP toolkit and the DB pools on exit (`:58-73`).

`AgentRunner` (`weebot/interfaces/cli/agent_runner.py`):
- `run_prompt` (`:97-245`): loads or creates the session, starts behavior tracking, builds tools once (`:69-74`), then `route_and_create_flow` when a router is set, else `create_flow("plan_act")` (`:169-210`); re-saves the flow's session at the end (`:226-238`).
- `resume_session` (`:247-314`) requires WAITING, sanitizes the answer (`:268-270`), runs the flow inline.
- `cancel_session` (`:350-356`) delegates to a `TaskRunner` built in the constructor (`:60`).

`create_flow` (`weebot/interfaces/factories.py:204-308`): `plan_act` resolves optional collaborators from the shared container through `_cached` (`:60-68`) and builds `PlanActFlow`; `chat` builds `ChatFlow`. `build_tools` (`:348-425`): registry from the container, sub-agent flow factory, MCP tools (configured servers via `_configured_mcp_tools`, `:109-141`), Apify presets when `APIFY_API_KEY` is set (`:399-412`), then `guard_tools` resolved from DI; no guard means `RuntimeError` (`:418-421`).

Consequences (read from source, not run):
- `pyproject.toml:26` declares `weebot = "cli.main:main"`, but `cli/main.py` defines no `main`; the module runs `_wrap_main()` only under `__main__` (`:752-753`). The installed `weebot` script cannot start.
- `flow run` and `flow resume` build `AgentRunner` with the container's bus (`cli/commands/flow.py:124, 184`), so the flow publishes events and domain events; the runner publishes only events the flow yielded without emitting (`weebot/interfaces/cli/agent_runner.py`, `_was_emitted`).
- `flow cancel` can only cancel a task in its own process: `TaskRunner.cancel_session` looks in the in-memory `_tasks` (`weebot/application/services/task_runner.py:348-359`), and the CLI's runner is new per command.
- `flow retry` returns False in a fresh process: `rerun_failed_session` pops a cached flow factory and returns False when there is none, though it logs "attempting resume with default factory" (`task_runner.py:383-391`).
- `flow undo` rebuilds a flow whose `PlanHistory` starts empty (`plan_act_flow.py:206`), so `undo()` returns None and the command always prints "Nothing to undo" (`weebot/application/services/plan_history.py:56-57`). It also omits `state_repo` (`agent_runner.py:326-336`).
- `_cached` swallows every exception with no log (`factories.py:65-68`); so does `_get_flow_factory` (`:344-345`). A missing collaborator turns into `None` silently. The sub-agent factory builds `PlanActFlow` with `tools=None` and no mediator (`:333-341`).
- `cron-agent` `_load_jobs` returns `{}` on any JSON error with no log (`cli/commands/cron_agent.py:35-39`); the next `create` then saves only the new job over the unreadable file (`:127-129`).
- The module docstring (`cli/main.py:2-16`) still lists the removed project commands; `_handle_cli_exceptions` is a no-op (`:140-143`).

## Connected to
- **Uses** the DI container (`application/DIContainer.md`), `PlanActFlow` (`application/PlanActFlow.md`), `RoleBasedToolRegistry` via `build_tools`, `SQLiteStateRepository` and the event store (`infrastructure/`).
- **Shares** `create_flow` / `build_tools` with the web routers (`weebot/interfaces/web/routers/sessions.py:289, 403`, `routers/webhook.py:124-125`) and every chat gateway (see `ChatGateways.md`). The container registers `create_flow` as a service (`weebot/application/di/__init__.py:255-266`) for `TaskRunner`, the scheduler (`weebot/scheduling/scheduler.py:636`) and `cron-agent run` (`cli/commands/cron_agent.py:269`).
- **Looks like but is not:** `run.py` (legacy REPL, also on `shared_container`, `run.py:156-158`); the MCP server (`MCPServer.md`); `cli mcp`, which edits the MCP client's server list.

## If you change this
**Hits:** every CLI command, the web and gateway flow construction (shared factories), tests `tests/unit/cli/test_flow_one_container.py`, `tests/unit/cli/test_flow_run_without_stdin.py`, `tests/unit/cli/test_ponytail_commands.py`, `tests/unit/fixes/test_w53_interface_roots.py`, `tests/unit/fixes/test_w53_container_construction.py`, `tests/unit/fixes/test_w53_completion_jobs.py`, `tests/unit/fixes/test_w53_tool_registry_collaborators.py`, `tests/unit/fixes/test_create_flow_persistence.py`, `tests/unit/fixes/test_mcp_toolkit_closed_on_exit.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/fixes/test_cron_agent_jobs_wired.py`, `tests/unit/fixes/test_w42_one_cost_query.py`, `tests/unit/interfaces/test_build_tools_configured_mcp.py`, `tests/unit/application/test_flow_construction_wiring.py`, `tests/unit/application/services/test_background_work_is_owned.py`, `tests/unit/test_bash_guard_cli.py`, `tests/unit/test_fts_search.py`, `tests/unit/test_profile_manager.py`, `tests/unit/tools/test_skill_cli.py`, `tests/unit/test_low_priority.py`, `tests/e2e/test_flow_e2e.py`.
**Does not hit:** the flow state machine itself; the web lifespan container (`WebAPI.md`), which is a different container.

## Surfaces
Humans at a terminal (`python -m cli.main ...`); scripts and CI (`flow run` with closed stdin).

## See
`cli/main.py`, `cli/commands/flow.py`, `weebot/interfaces/factories.py`
