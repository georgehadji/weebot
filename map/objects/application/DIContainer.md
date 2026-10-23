---
type: object
name: DI Container
code: Container
cluster: application
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# DI Container

A small service locator. It maps a port type (or a string key) to a lazy factory, builds each thing once, and holds the composition root's wiring: which adapter backs which port, how the Mediator and its handlers are assembled, how flows and the step executor are constructed.

## Why this shape
Bindings are factories so adapters that a process never uses (a browser in a CLI-only run) are never built (`weebot/application/di/__init__.py:77-81`). The class is a dataclass assembled from mixins, so factory methods live beside their topic: `FactoriesMixin` (`_factories.py`), `AgentToolsMixin`, `CapabilitiesMixin`, `SkillsMixin`, `SkillOptMixin`, `LearningMixin` (`:56-76`). Many adapters are imported lazily inside factories to keep application code from importing infrastructure at module load (the lint contracts depend on that).

## Shape
- State: `_bindings` (type or string key to factory) and `_singletons` (key to instance) (`:88-89`).
- `register`, `register_instance`, `get` (`:93-115`): `get` returns the singleton, else calls the factory once and caches it; no binding raises `KeyError("No binding registered for X")`.
- `_maybe_get` and `_maybe_get_str` swallow `KeyError` and return `None` (`:587-599`).
- `configure_defaults(db_path, default_model)` (`:130-351`): 52 `self.register(...)` calls in the file (state repo, event bus, tracing, LLM, sandbox, Mediator, task runner, event store, tool repo, `WeebotSettings` and `ToolConfig` (`:132-137`), many string-keyed items such as `"skill_retriever"`, `"personality"`, `"llm_pool"`, `"mcp_client"`), then `configure_knowledge_graph` and `configure_learning` (`:348-351`).
- `step_executor(model, session, context, ...)` builds the `ExecutorAgent` that runs one plan step: container singletons first, then every field of the flow's `StepExecutionContext` via `context.executor_kwargs()` (ADR-015, F25) (`:425-464`).
- `build_mediator` (`:466-556`): adds `ValidationBehavior`, `LoggingBehavior`, `TelemetryBehavior`, `SavePolicyBehavior` (`:471-477`); builds the admin `ToolCollection`, and on failure logs a warning, runs **tool-less** and records `mediator.degraded["tools"]` (`:482-509`); resolves `ScoringPort` by type (`:510-517`); defines `_executor_factory`, which calls `step_executor` (`:529-541`); calls `register_default_handlers` (`:543-555`).
- `build_flow_registry` registers `plan_act` and `chat` flows (`:355-401`); `build_scheduler` (`:403`), `build_agent_runner` (`:409-423`), `build_chat_flow` (`:558`), `build_hyper_agent_flow` (`:668`).
- `warm_up` builds the Mediator up front, because constructing it builds the role LLM adapters and tool registry, "tens of seconds on a cold start" (`:117-126`).
- `validate()` resolves every type-keyed binding and returns error strings; string keys are skipped (`:689-700`).

## Connected to
- **Creates:** the Mediator (`_create_mediator` calls `build_mediator`, `weebot/application/di/_factories.py:119-120`), every flow, the step executor, and the ports' adapters.
- **Shared root:** `weebot/interfaces/factories.py:71-88` (`shared_container()`, one configured container per process), used by the web lifespan (`weebot/interfaces/web/main.py:186-188`) and the CLI (`cli/main.py:76-88`).
- **Hand-built elsewhere:** 8 `Container()` sites outside `di/`, held at that ceiling by `scripts/lint_container_construction.py` (`tasks/quality/ceilings.toml:265-277`): `weebot/core/agent.py:45`, `weebot/interfaces/factories.py:84`, `cli/commands/flow.py:332`, `cli/commands/harness.py:55, 95, 254, 350`, `run_mcp.py:58`. Each `Container()` has its own empty bindings and singletons, so it only works after `configure_defaults()`.
- **Checked by:** `scripts/lint_di_wiring.py` (`make lint-di-wiring`) and `tests/unit/test_architecture_fitness.py`.
- **Looks like but is not:** a framework container; there is no scope, no auto-wiring, no constructor injection. It is looked up by hand.

## If you change this
**Hits:** every consumer of `get(...)`/`_maybe_get(...)`; all flow construction sites (see PlanActFlow); the Mediator and every handler; the step executor and `StepExecutionContext`; `lint_di_wiring.py`, `lint_container_construction.py` and their ceilings; tests `tests/unit/application/test_flow_construction_wiring.py`, `tests/unit/application/di/test_mcp_di_factories.py`, `tests/unit/test_learning_di_bindings.py`, `tests/unit/application/test_bulkheads.py`, `tests/unit/fixes/test_w54_step_execution_context.py`, `tests/unit/fixes/test_w53_interface_roots.py`.
**Does not hit:** adapters' own behavior; the flow state machine. Changing a binding key hits string-keyed lookups silently: `_maybe_get_str` returns `None` (the source records a bug of that shape at `:510-514`).

## Surfaces
Process start-up: the web server calls `warm_up` (`weebot/interfaces/web/main.py:229`). The CLI takes `shared_container()` and builds `AgentRunner` itself (`cli/commands/flow.py:116`); `build_agent_runner` is called only by a test (`tests/unit/fixes/test_w53_interface_roots.py:61`).

## See
`weebot/application/di/__init__.py`
