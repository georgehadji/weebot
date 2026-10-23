---
type: object
name: Mediator (CQRS)
code: Mediator
cluster: application
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# Mediator

A dispatcher that maps a command or query *type* to one registered handler and runs the call through a chain of pipeline behaviors. States do not call agents; they `send` a command and the handler does the work. `send(command)` returns a `CommandResult`; `query(query)` returns a `QueryResult`.

## Why this shape
Decouples the flow states from the agents and persistence they trigger (`weebot/application/cqrs/mediator.py:37-42`). Failures never raise out of `send`: any handler exception becomes `CommandResult.fail(error, error_code=<exception class name>)` (`:218-229`), so callers check `result.success`. Commands and queries are frozen Pydantic models with `extra="forbid"` (`cqrs/base.py:39, 62`).

## Shape
- Registries: `_command_handlers` and `_query_handlers`, one handler per type; registering twice raises `ValueError` (`:95-96, 110-111`); `unregister_*` exists (`:115-131`).
- `send` (`:179`) wraps `_send_inner` in a tracing span `command.<Name>`; a missing handler returns `HANDLER_NOT_REGISTERED` instead of raising (`:197-201`). A handler may return a bare value, which is wrapped with `CommandResult.ok` (`:213-216`).
- `query` (`:231`) is the same, but a `None` result becomes `QueryResult.not_found()` and every exception becomes `QueryResult.fail(str(e))` (`:266-272`).
- Pipeline: behaviors run in insertion order, each calling `next` (`_execute_with_pipeline`, `:153-177`). Adding behaviors is "NOT thread-safe — call at startup only" (`:137`).
- The tracer is resolved lazily by building a **new** `Container()` and calling `configure_defaults()` (`:72-81`).

What exists (2026-10-21):
- Commands: `CreatePlanCommand`, `ExecuteStepCommand`, `UpdatePlanCommand`, `SummarizeCommand`, `ProcessMessageCommand` (`cqrs/commands.py:19-65`), plus SkillOpt and Self-Harness commands registered only by `register_skillopt_handlers` (`cqrs/handlers/__init__.py:164-264`).
- Queries: `GetActiveSessionsQuery`, `GetPlanVisualizationQuery`, `GetCostSummaryQuery` (`cqrs/queries.py`); `ClusterFailurePatternsQuery` is SkillOpt-only.
- Behaviors: `ValidationBehavior`, `LoggingBehavior`, `TelemetryBehavior`, `SavePolicyBehavior` added in that order by `Container.build_mediator` (`di/__init__.py:417-422`); `ValidationGateBehavior` is added only for the SkillOpt flow (`di/_skillopt.py:49-51`).
- Default registration: `register_default_handlers` (`cqrs/handlers/__init__.py:80`). When `llm` is `None` the plan commands get validation-only handlers (`:137-140`); `SummarizeCommand` is registered only with an `llm` (`:141-142`); `ScoreTrajectoryCommand` only if scoring port and trajectory builder exist (`:148-154`).

## Connected to
- **Built and owned by** the DI Container (`Container.build_mediator`, `di/__init__.py:412`), as a singleton per container.
- **Callers (`.send`):** `PlanningState` (`states/planning.py:192`), `ExecutingState` (`:447`), `UpdatingState` (`:110`), `SummarizingState` (`:33`), `CompletedState` (`:282`), `ChatMessageState` (`:56`), `SkillOptFlow` (`flows/skill_opt_flow.py:191,267`), and `ScoreTrajectoryHandler` (`handlers/trajectory_handler.py:91`). **`.query`:** `interfaces/web/routers/ops_router.py` (all three endpoints, since W7.1). Planning and Executing refuse to run with no mediator (`planning.py:82`, `executing.py:430`).
- **Handlers that build agents:** `CreatePlanHandler` → PlannerAgent, `ExecuteStepHandler` → ExecutorAgent, `UpdatePlanHandler` → PlannerAgent, `SummarizeHandler` → ExecutorAgent (see those cards).
- **Looks like but is not:** the event bus (`EventBusPort`, publishes events, no handlers per type); `MiddlewareChain` inside `ExecutorAgent` (wraps LLM requests, not commands).

## Fixed defect: F22 (W7.1, 2026-10-22)
`ops_router` passed its three queries to `mediator.send`, which looks only in `_command_handlers`, so every endpoint answered HTTP 500 (the Plan panel's "Internal server error"). It also built and configured a new `Container()` per request. Now each endpoint calls `mediator.query` and takes the mediator and state repo from the lifespan container on `app.state` through `Depends` (`ops_router.get_mediator`, `get_state_repo`). Test: `tests/unit/fixes/test_f22_ops_router_dispatch.py` (4). Since W5.2, `send` raises `TypeError` for a `Query` and `query` for a `Command`.

## Construction (W5.2)
`Mediator(tracer=None)`: `build_mediator` (`application/di/__init__.py`) passes the container's `TracingAdapter`; with none, requests run without spans. `mediator.degraded` maps a part that failed to build to the error; today only `"tools"` (the admin tool set), which `/health` reports as `agent_tools` (`interfaces/web/routers/health.py`).

## If you change this
**Hits:** every state that sends a command; all handler registrations; the pipeline behaviors (they see every request); the error contract (`error_code` is the exception class name, callers may match on it); tests `tests/unit/test_cqrs_persistence.py`, `tests/unit/test_planning.py`, `tests/unit/application/flows/test_a_failed_plan_is_not_a_success.py`, `tests/unit/application/flows/test_a_failed_plan_update_is_not_progress.py`, `tests/unit/application/test_flow_construction_wiring.py`.
**Does not hit:** the event bus; flow state transitions themselves; LLM adapters.

## Surfaces
Internal. Reached from the CLI, web and MCP only through flows. The `GetActiveSessionsQuery` / `GetCostSummaryQuery` family feeds the operations console (comment at `cqrs/handlers/__init__.py:156`).

## See
`weebot/application/cqrs/mediator.py`
