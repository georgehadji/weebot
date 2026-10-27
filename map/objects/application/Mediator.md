---
type: object
name: Mediator (CQRS)
code: Mediator
cluster: application
universe: live
status: verified
verified: 2026-10-27
commit: 0034f08b
---

# Mediator

A dispatcher that maps a command or query *type* to one registered handler and runs the call through a chain of pipeline behaviors. States do not call agents; they `send` a command and the handler does the work. `send(command)` returns a `CommandResult`; `query(query)` returns a `QueryResult`.

## Why this shape
Decouples the flow states from the agents and persistence they trigger (`weebot/application/cqrs/mediator.py:53-58`). Failures never raise out of `send`: any handler exception is logged with its `ErrorClassifier` category and becomes `CommandResult.fail(error, error_code=<exception class name>)` (`:239-250`), so callers check `result.success`. Commands and queries are frozen Pydantic models with `extra="forbid"` (`weebot/application/cqrs/base.py:39, 62`).

## Shape
- `Mediator(tracer=None)` (`:81-95`): `_command_handlers` and `_query_handlers`, one handler per type; registering twice raises `ValueError` (`:100-130`); `unregister_*` exists (`:132-148`). With no tracer, requests run inside no-op spans (`:28-38, 97-98`).
- `degraded` maps a part that failed to build to its error; `build_mediator` sets `"tools"` when the admin tool set fails (`:93-95`, `weebot/application/di/__init__.py:560`), and `/health` reports it as `agent_tools` (`weebot/interfaces/web/routers/health.py:187-192`).
- `send` (`:196-211`) raises `TypeError` for a `Query`, then wraps `_send_inner` in a tracing span `command.<Name>`. A missing handler returns `HANDLER_NOT_REGISTERED` instead of raising (`:218-222`). A handler may return a bare value, which is wrapped with `CommandResult.ok` (`:234-237`).
- `query` (`:252-265`) raises `TypeError` for a `Command`; otherwise the same, but a `None` result becomes `QueryResult.not_found()` and every exception becomes `QueryResult.fail(str(e))` (`:267-295`).
- Pipeline: behaviors run in insertion order, each calling `next` (`_execute_with_pipeline`, `:170-194`). Adding behaviors is "NOT thread-safe — call at startup only" (`:150-159`).

What exists (2026-10-24):
- Commands: `CreatePlanCommand`, `ExecuteStepCommand`, `UpdatePlanCommand`, `SummarizeCommand`, `ProcessMessageCommand` (`weebot/application/cqrs/commands.py:19-89`); the live mediator also counts candidate-skill uses (`RecordSkillUseCommand`) and, with an LLM and a trajectory repository, extracts failure signatures. The `commands/` package shadows that module and loads it by file path to re-export them (`weebot/application/cqrs/commands/__init__.py:1-32`). SkillOpt and Self-Harness commands are registered only by `register_skillopt_handlers` (`weebot/application/cqrs/handlers/__init__.py:190-292`).
- Queries: `GetActiveSessionsQuery`, `GetPlanVisualizationQuery`, `GetCostSummaryQuery` (`weebot/application/cqrs/queries.py:22, 38, 47`); `ClusterFailurePatternsQuery` is SkillOpt-only (`cqrs/commands/failure_signature_commands.py:56`).
- Behaviors: `ValidationBehavior`, `LoggingBehavior`, `TelemetryBehavior`, `SavePolicyBehavior` added in that order by `Container.build_mediator` (`di/__init__.py:523-529`); a validation gate behavior is added only for the SkillOpt flow (`weebot/application/di/_skillopt.py:49-52`).
- Default registration: `register_default_handlers` (`handlers/__init__.py:86`). With an `llm`, plan, execute, update and `ProcessMessageCommand` handlers get the LLM (`:118-137`); with `llm=None` only the three plan commands get validation-only handlers (`:138-141`). `SummarizeCommand` is registered only with an `llm` (`:142-143`); `ScoreTrajectoryCommand` only if scoring port and trajectory builder exist (`:149-155`). The three operations-console queries are always registered (`:157-161`).

## Connected to
- **Built and owned by** the DI Container (`Container.build_mediator`, `di/__init__.py:518-609`), as a singleton per container.
- **Callers (`.send`):** `PlanningState` (`weebot/application/flows/states/planning.py:228`), `ExecutingState` (`weebot/application/flows/states/_step_run.py:71`), `UpdatingState` (`states/updating.py:117`), `SummarizingState` (`states/summarizing.py:34`), `CompletedState` (`states/completed.py:314`), `ChatMessageState` (`states/chat_message.py:56`), `SkillOptFlow` (`weebot/application/flows/skill_opt_flow.py:191, 267`), and `ScoreTrajectoryHandler` (`cqrs/handlers/trajectory_handler.py:94`). **`.query`:** `weebot/interfaces/web/routers/ops_router.py:48, 72, 96`, which takes the mediator and state repo from the app's container through `Depends` (`:28-36`). Planning and Executing refuse to run with no mediator (`planning.py:95`, `executing.py:141`).
- **Handlers that build agents:** `CreatePlanHandler` builds PlannerAgent, `ExecuteStepHandler` builds ExecutorAgent through the container's executor factory, `UpdatePlanHandler` builds PlannerAgent, `SummarizeHandler` builds ExecutorAgent (see those cards).
- **Looks like but is not:** the event bus (`EventBusPort`, publishes events, no handler per type); `MiddlewareChain` inside `ExecutorAgent` (wraps LLM requests, not commands).

## If you change this
**Hits:** every state that sends a command; all handler registrations; the pipeline behaviors (they see every request); the error contract (`error_code` is the exception class name, callers may match on it); the ops router and `/health`; tests `tests/unit/test_cqrs_persistence.py`, `tests/unit/test_planning.py`, `tests/unit/application/flows/test_a_failed_plan_is_not_a_success.py`, `tests/unit/application/flows/test_a_failed_plan_update_is_not_progress.py`, `tests/unit/application/test_flow_construction_wiring.py`, `tests/unit/fixes/test_f22_ops_router_dispatch.py`.
**Does not hit:** the event bus; flow state transitions themselves; LLM adapters.

## Surfaces
Internal. Reached from the CLI, web and MCP only through flows, except the operations console, which queries it directly (`ops_router.py:48-96`).

## See
`weebot/application/cqrs/mediator.py`
