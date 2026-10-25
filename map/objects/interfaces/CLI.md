---
type: object
name: CLI
code: cli (click group), AgentRunner, interfaces.factories
cluster: interfaces
universe: live
status: stale
verified: 2026-10-24
commit: eeb0e80e
---

# CLI

The `python -m cli.main` click application: one root group `cli` (`cli/main.py:132-137`) plus command groups imported from `cli/commands/` and `weebot/interfaces/cli/`. Agent runs go through `AgentRunner` (`weebot/interfaces/cli/agent_runner.py:48`), which builds tools and flows with `create_flow` / `build_tools` in `weebot/interfaces/factories.py`.

## Why this shape
Each command group lives in its own module and is attached with `cli.add_command` at the bottom of `cli/main.py` (`cli/main.py:710-747`), so `cli/main.py` keeps only ops commands (init, doctor, health, costs, hooks, upgrades). Every entry point is meant to share one DI container per process: `shared_container()` (`weebot/interfaces/factories.py:54-70`), built lazily under a lock; `reset_shared_container()` forgets it for tests and does not close what the old one opened (`:73-81`). The same factories module serves the web routers and the chat gateways, so the CLI and the server build flows the same way.

## Shape
Root commands in `cli/main.py`:

| Command | Line | What it does |
|---|---|---|
| `create`, `status`, `run`, `resume`, `checkpoint` | `cli/main.py:169-228` | print "deprecated, use flow"; nothing else |
| `list-projects` | `cli/main.py:177-195` | `state_repo.list_sessions()` from the shared container; prints `session.id` (`:190`; it read `session_id` and raised until 2026-10-24, `tests/unit/fixes/test_minor_fix_retry_and_list_projects.py`) |
| `delete` | `cli/main.py:231-240` | prints that projects no longer exist and nothing was removed, exits 1 |
| `export` | `cli/main.py:243-257` | dumps one session to JSON |
| `costs` | `cli/main.py:266-291` | `GetCostSummaryHandler` over a fresh `EventStore()` (`:260-263`) |
| `init`, `doctor`, `health` | `cli/main.py:306-513` | `init_project` / `run_doctor` from `weebot/interfaces/cli/support.py:52, 212`; `health` adds a model ping (`cli/main.py:457-461`) |
| `hooks init/install`, `check-updates`, `upgrade`, `implement` | `cli/main.py:516-626` | support helpers; `implement` only writes a plan JSON |
| `research init-experiment/validate-data/obsidian-sync` | `cli/main.py:295-699` | imports `research_modules`, `integrations.obsidian` |

Groups registered at `cli/main.py:710-747`:

| Group | Module | Wires |
|---|---|---|
| `flow` (run, resume, list, cancel, retry, undo, skillopt, export, search, decisions) | `cli/commands/flow.py:117-492` | `AgentRunner` with its LLM from `_cli_llm` (`:88-101`), state repo and `Mediator` from the shared container (`:78-93`); `_cli_llm` resolves the port through `Container.create_llm_for_model` (`application/di/_factories.py:144-159`), so it is wrapped in `BoundedLLMAdapter` (`infrastructure/LLMAdapters.md`); `skillopt` builds its own `Container()` (`:332`) |
| `hyper` | `cli/commands/hyper.py:27` | shared container (`:44-46`), `event_bus=container.get(EventBusPort)` (`:60`) |
| `skill`, `agents`, `profile`, `cron`, `companion`, `guard`, `analytics`, `soul`, `dream`, `mcp`, `gateway`, `cron-agent`, `auth`, `ponytail*` | `cli/commands/*.py` | see each module; `mcp` manages the MCP client config, not the MCP server |
| `benchmark`, `harness` | `cli/commands/harness.py:12, 142` | each builds its own `Container()` (`:55, 95, 256, 352`), not the shared one |
| `behavior` | `weebot/interfaces/cli/behavior_commands.py:17` | file-change ledger: watch, status, stop, report, trust, log, override, reflect, summary, reset, doctor |

`flow run` (`cli/commands/flow.py:101-163`): streams `runner.run_prompt`, and on each `WaitForUserEvent` reads an answer with `asyncio.to_thread(input)`; on EOF it leaves the session WAITING and prints the resume command (`:142-152`); `runner.close()` tears the tools down, browser included (`:160-161`). `_run_async` (`:28-76`) installs `ConsoleApproval` when stdin is a TTY (`:45-56`), then drains background tasks (owner `weebot/core/background_tasks.py`, imported through the re-export at `:60, 70`), closes the MCP toolkit and the DB pools on exit (`:57-74`).

`AgentRunner` (`weebot/interfaces/cli/agent_runner.py`):
- `run_prompt` (`weebot/interfaces/cli/agent_runner.py:119-262`): loads or creates the session, starts behavior tracking, builds tools once (`:91-96`), then `route_and_create_flow` when a router is set, else `create_flow("plan_act")` (`:191-232`); re-saves the flow's session at the end (`:247-255`).
- `resume_session` (`:264-326`) requires WAITING (`:279`), sanitizes the answer (`:285-287`), runs the flow inline.
- `cancel_session` (`:362-368`) delegates to a `TaskRunner` built in the constructor (`:76`). `close` (`:85-89`) runs `ToolCollection.teardown()` and drops the collection.

`create_flow` (`weebot/interfaces/factories.py:214-246`) only passes `_cached` to `build_flow` (`weebot/application/flows/flow_builder.py:55-171`), which resolves the optional collaborators and builds `PlanActFlow` (`:95-158`) or `ChatFlow` (`:159-170`); the DI `create_flow` binding uses the same builder with the container as resolver (`weebot/application/di/__init__.py:239-278`). `build_tools` (`factories.py:262-338`): registry from the container (`:273`), sub-agent flow factory (`:282`), MCP tools (configured servers via `_configured_mcp_tools`, `:103-135`), Apify presets when `APIFY_API_KEY` is set (`:313-326`), then `guard_tools` resolved from DI; no guard means `RuntimeError` (`:332-335`).

Consequences (read from source, not run):
- `pyproject.toml:26` declares `weebot = "cli.main:_wrap_main"`, the wrapper `cli/main.py:146` defines and also runs under `__main__` (`cli/main.py:755-756`).
- `flow run` and `flow resume` build `AgentRunner` with the container's bus (`cli/commands/flow.py:139, 198`), so the flow publishes events and domain events; the runner publishes only events the flow yielded without emitting (`_was_emitted`, `weebot/interfaces/cli/agent_runner.py:43-45, 243-244`).
- `flow cancel` first tries its own process: `TaskRunner.cancel_session` looks in the in-memory `_tasks` (`weebot/application/services/task_runner.py:396-407`), empty in a fresh CLI. Otherwise, for a RUNNING, WAITING or PENDING session, it files a cross-process cancel request and marks a non-RUNNING session FAILED (F77, `cli/commands/flow.py:250-269`).
- `flow retry` returns False in a fresh process: `rerun_failed_session` pops a cached flow factory and returns False when there is none, though it logs "attempting resume with default factory" (`task_runner.py:431-439`). The command now says so: retry works only in the process that ran the session (`cli/commands/flow.py:300-305`).
- `flow undo` rebuilds a flow whose `PlanHistory` starts empty (`plan_act_flow.py:214`), so `undo()` returns None and the command always prints "Nothing to undo" (`weebot/application/services/plan_history.py:55-56`). It also omits `state_repo` (`agent_runner.py:338-348`).
- `_cached` swallows every exception with no log (`factories.py:48-51`); so does `_get_flow_factory` (`:258-259`). A missing collaborator turns into `None` silently. The sub-agent factory builds `PlanActFlow` with `tools=None` and no mediator, and returns `None` when the shared state repo or bus is missing (`:238-255`).
- `cron-agent` `_load_jobs` moves an unreadable jobs file aside as `cron_jobs.json.corrupt-<time>`, logs and prints it, then returns `{}`, so the next save does not overwrite the old jobs (F77, `cli/commands/cron_agent.py:35-48`).
- The module docstring (`cli/main.py:2-16`) still lists the removed project commands; `_handle_cli_exceptions` is a no-op (`cli/main.py:140-143`).

## Connected to
- **Uses** the DI container (`application/DIContainer.md`), `PlanActFlow` (`application/PlanActFlow.md`), `RoleBasedToolRegistry` via `build_tools`, `SQLiteStateRepository` and the event store (`infrastructure/`).
- **Shares** `create_flow` / `build_tools` with the web routers (`weebot/interfaces/web/routers/sessions.py:339, 453`, `routers/webhook.py:128-129`) and every chat gateway (see `ChatGateways.md`). The container registers `create_flow` as a service (`weebot/application/di/__init__.py:259-278`) for `TaskRunner`, the scheduler (`weebot/scheduling/scheduler.py:636`) and `cron-agent run` (`cli/commands/cron_agent.py:276`).
- **Looks like but is not:** `run.py` (legacy REPL, also on `shared_container`, `run.py:151-153`); the MCP server (`MCPServer.md`); `cli mcp`, which edits the MCP client's server list.

## If you change this
**Hits:** every CLI command, the web and gateway flow construction (shared factories), tests `tests/unit/cli/test_flow_one_container.py`, `tests/unit/cli/test_flow_run_without_stdin.py`, `tests/unit/cli/test_ponytail_commands.py`, `tests/unit/fixes/test_w53_interface_roots.py`, `tests/unit/fixes/test_w53_container_construction.py`, `tests/unit/fixes/test_w53_completion_jobs.py`, `tests/unit/fixes/test_w53_tool_registry_collaborators.py`, `tests/unit/fixes/test_create_flow_persistence.py`, `tests/unit/fixes/test_mcp_toolkit_closed_on_exit.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/fixes/test_cron_agent_jobs_wired.py`, `tests/unit/fixes/test_w42_one_cost_query.py`, `tests/unit/interfaces/test_build_tools_configured_mcp.py`, `tests/unit/application/test_flow_construction_wiring.py`, `tests/unit/application/services/test_background_work_is_owned.py`, `tests/unit/test_bash_guard_cli.py`, `tests/unit/test_fts_search.py`, `tests/unit/test_profile_manager.py`, `tests/unit/tools/test_skill_cli.py`, `tests/unit/test_low_priority.py`, `tests/unit/fixes/test_cli_delete_does_not_lie.py`, `tests/unit/fixes/test_cli_flow_commands_explain.py`, `tests/unit/fixes/test_cron_jobs_file_is_not_lost.py`, `tests/unit/fixes/test_cross_process_cancel.py`, `tests/e2e/test_flow_e2e.py`.
**Does not hit:** the flow state machine itself; the web lifespan container (`WebAPI.md`), which is a different container.

## Surfaces
Humans at a terminal (`python -m cli.main ...`); scripts and CI (`flow run` with closed stdin).

## See
`cli/main.py`, `cli/commands/flow.py`, `weebot/interfaces/factories.py`
