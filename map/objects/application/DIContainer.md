---
type: object
name: DI Container
code: Container
cluster: application
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# DI Container

A small service locator. It maps a port type (or a string or typed `Key[T]` key) to a lazy factory, builds each thing once, and holds the composition root's wiring: which adapter backs which port, how the Mediator and its handlers are assembled, how flows and the step executor are constructed.

## Why this shape
Bindings are factories so adapters that a process never uses (a browser in a CLI-only run) are never built (`weebot/application/di/__init__.py:83-90`). The class is a dataclass assembled from mixins, so factory methods live beside their topic: `FactoriesMixin` (`_factories.py`), `AgentToolsMixin`, `CapabilitiesMixin`, `SkillsMixin`, `SkillOptMixin`, `LearningMixin` (`weebot/application/di/__init__.py:83-85`). Many adapters are imported lazily inside factories to keep application code from importing infrastructure at module load (the lint contracts depend on that).

## Shape
- State: `_bindings` (type or string key to factory) and `_singletons` (key to instance) (`weebot/application/di/__init__.py:97-98`).
- `register`, `register_instance`, `get` (`weebot/application/di/__init__.py:102-122`): `get` returns the singleton, else calls the factory once and caches it; no binding raises `KeyError("No binding registered for X")`.
- `_maybe_get` and `_maybe_get_str` swallow `KeyError` and return `None` (`weebot/application/di/__init__.py:639-650`).
- `configure_defaults(db_path, default_model)` (`weebot/application/di/__init__.py:139-407`): 56 `self.register(...)` calls in the file (state repo, event bus, tracing, LLM, sandbox, Mediator, task runner, event store, tool repo, `ApiKeyPort`, `WeebotSettings` and `ToolConfig` (`weebot/application/di/__init__.py:145-146`), many string-keyed items such as `"skill_retriever"`, `"personality"`, `"mcp_client"`, `"tool_registry"` (`weebot/application/di/__init__.py:401`)), then `configure_knowledge_graph` and `configure_learning` (`weebot/application/di/__init__.py:405-407`). `create_flow` is a builder over `flows/flow_builder.py:build_flow` (`_create_flow_callable`, `weebot/application/di/__init__.py:262-281`). Typed keys `LLM_POOL` and `SESSION_COST_METER` come from `weebot/application/di/keys.py:43-44`; the `string_di_keys` ratchet (`tasks/quality/ceilings.toml:407`) counts the string keys left.
- `step_executor(model, session, context, ...)` builds the `ExecutorAgent` that runs one plan step: container singletons first, then every field of the flow's `StepExecutionContext` via `context.executor_kwargs()` (ADR-015, F25) (`weebot/application/di/__init__.py:465-515`); it also wires the pool, effect ledger, cost meter, memory snapshot and `ACR_ROUTER` (`weebot/application/di/__init__.py:501-510`).
- `build_mediator` (`weebot/application/di/__init__.py:516-608`): adds `ValidationBehavior`, `LoggingBehavior`, `TelemetryBehavior`, `SavePolicyBehavior` (`weebot/application/di/__init__.py:522-527`); builds the admin `ToolCollection` from `RoleBasedToolRegistry` (`application/services/tool_registry.py`) and on failure logs a warning, runs **tool-less** and records `mediator.degraded["tools"]` (`weebot/application/di/__init__.py:529-559`); resolves `ScoringPort` by type (`weebot/application/di/__init__.py:560-567`); defines `_executor_factory`, which calls `step_executor` (`weebot/application/di/__init__.py:579`); calls `register_default_handlers` (`weebot/application/di/__init__.py:593-607`).
- `build_flow_registry` registers `plan_act` and `chat` flows (`weebot/application/di/__init__.py:411-457`); `build_scheduler` (`weebot/application/di/__init__.py:459`), `build_chat_flow` (`weebot/application/di/__init__.py:610`), `build_hyper_agent_flow` (`weebot/application/di/__init__.py:723`). `build_agent_runner` is gone (plan 3.7): flow assembly lives in `flow_builder.py`, which the container reaches without importing `interfaces`.
- `warm_up` builds the Mediator up front, because constructing it builds the role LLM adapters and tool registry, "tens of seconds on a cold start" (`weebot/application/di/__init__.py:126-136`).
- `validate()` resolves every type-keyed binding and returns error strings; string keys are skipped (`weebot/application/di/__init__.py:744-755`).

## Connected to
- **Creates:** the Mediator (`_create_mediator` calls `build_mediator`, `weebot/application/di/_factories.py:175-176`), every flow, the step executor, and the ports' adapters.
- **Shared root:** `weebot/interfaces/factories.py:56-73` (`shared_container()`, one configured container per process; `reset_shared_container` at `weebot/interfaces/factories.py:75-83`), used by the web lifespan (`weebot/interfaces/web/main.py:188-190`) and the CLI (`cli/main.py:76-88`).
- **Hand-built elsewhere:** 7 `Container()` sites outside `di/`, held at that ceiling by `scripts/lint_container_construction.py` (`tasks/quality/ceilings.toml:339`): `weebot/interfaces/factories.py:69`, `cli/commands/flow.py:405`, `cli/commands/harness.py:102, 143, 311, 410`, `run_mcp.py:58`. Each `Container()` has its own empty bindings and singletons, so it only works after `configure_defaults()`.
- **Checked by:** `scripts/lint_di_wiring.py` (`make lint-di-wiring`) and `tests/unit/test_architecture_fitness.py`.
- **Looks like but is not:** a framework container; there is no scope, no auto-wiring, no constructor injection. It is looked up by hand.

## If you change this
**Hits:** every consumer of `get(...)`/`_maybe_get(...)`; all flow construction sites (see PlanActFlow); the Mediator and every handler; the step executor and `StepExecutionContext`; `lint_di_wiring.py`, `lint_container_construction.py` and their ceilings; tests `tests/unit/application/test_flow_construction_wiring.py`, `tests/unit/application/di/test_mcp_di_factories.py`, `tests/unit/test_learning_di_bindings.py`, `tests/unit/application/test_bulkheads.py`, `tests/unit/fixes/test_w54_step_execution_context.py`, `tests/unit/fixes/test_w53_interface_roots.py`.
**Does not hit:** adapters' own behavior; the flow state machine. Changing a binding key hits string-keyed lookups silently: `_maybe_get_str` returns `None` (the source records a bug of that shape at `weebot/application/di/__init__.py:560-566`).

## Surfaces
Process start-up: the web server calls `warm_up` (`weebot/interfaces/web/main.py:240`). The CLI takes `shared_container()` and builds `AgentRunner` itself (`cli/commands/flow.py:131`).

## See
`weebot/application/di/__init__.py`
