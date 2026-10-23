---
type: object
name: DI Container
code: Container
cluster: application
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# DI Container

A small service locator. It maps a port type (or a string key) to a lazy factory, builds each thing once, and holds the composition root's wiring: which adapter backs which port, how the Mediator and its handlers are assembled, how flows are constructed.

## Why this shape
Bindings are factories so adapters that a process never uses (a browser in a CLI-only run) are never built (`weebot/application/di/__init__.py:72-82`). The class is a dataclass assembled from mixins, so factory methods live beside their topic: `FactoriesMixin` (`_factories.py`), `AgentToolsMixin`, `CapabilitiesMixin`, `SkillsMixin`, `SkillOptMixin`, `LearningMixin` (`:72-74`). Many adapters are imported lazily inside factories to keep application code from importing infrastructure at module load (the lint contracts depend on that).

## Shape
- State: `_bindings` (type → factory) and `_singletons` (type → instance) (`:88-89`).
- `register`, `register_instance`, `get` (`:91-113`): `get` returns the singleton, else calls the factory once and caches it; no binding raises `KeyError("No binding registered for X")`.
- `configure_defaults(db_path, default_model)` (`:128`): about 50 `self.register(...)` calls (state repo, event bus, tracing, LLM, sandbox, Mediator, task runner, event store, tool repo, rerank, many string-keyed items such as `"skill_retriever"`, `"personality"`, `"llm_pool"`), then `configure_knowledge_graph` and `configure_learning` (`:338-340`).
- `build_mediator` (`:412`): adds behaviors, builds the admin `ToolCollection` (on failure logs a warning and runs **tool-less**, `:441-450`), defines `_executor_factory` (`:472-500`) and calls `register_default_handlers` (`:502-513`).
- `build_flow_registry` registers `plan_act` and `chat` flows (`:344-389`); `build_agent_runner` (`:397`), `build_chat_flow` (`:516`), `build_hyper_agent_flow` (`:634`).
- `warm_up` builds the Mediator up front, because constructing it builds the role LLM adapters and tool registry and "tens of seconds on a cold start" (`:115-126`).
- `validate()` resolves every type-keyed binding and returns error strings (`:655-666`); string keys are skipped.

Important consequence, in the source's own words: `PlanActFlow._executor` "only serves the summarize fallback"; steps run through the Mediator, and `_executor_factory` builds that executor. It receives only container-level singletons. Per-flow and per-session values (skill prompt, agent role, harness block, behavioral learner, middleware chain, trajectory config) are **not** available there (`:462-471, 488-497`).

## Connected to
- **Creates:** the Mediator (`_create_mediator` → `build_mediator`, `_factories.py:119`), every flow, and the ports' adapters.
- **Constructed in many places:** about a dozen sites outside `di/` call `Container()` directly, for example `core/agent.py:45`, `flows/chat_flow.py:69`, `flows/states/completed.py:57,106`, `executor/_tool_executor.py:107`, `cqrs/mediator.py:78`, `interfaces/cli/agent_runner.py:65`, `interfaces/factories.py:71,122`. Each `Container()` has its own empty bindings and singletons, so it only works after `configure_defaults()` (which `mediator.py:79` does).
- **Checked by:** `scripts/lint_di_wiring.py` (every binding must be resolved by something or named an orphan; `make lint-di-wiring`) and `tests/unit/test_architecture_fitness.py`.
- **Looks like but is not:** a framework container; there is no scope, no auto-wiring, no constructor injection. It is looked up by hand.

## If you change this
**Hits:** every consumer of `get(...)`/`_maybe_get(...)`; all flow construction sites (see PlanActFlow); the Mediator and every handler; `lint_di_wiring.py` and its ceiling; tests `tests/unit/application/test_flow_construction_wiring.py`, `tests/unit/application/di/test_mcp_di_factories.py`, `tests/unit/test_learning_di_bindings.py`, `tests/unit/application/test_bulkheads.py`.
**Does not hit:** adapters' own behavior; the flow state machine. Changing a binding key hits string-keyed lookups silently: `_maybe_get_str` swallows `KeyError` and returns `None` (the source records a bug of that shape at `:451-455`).

## Surfaces
Process start-up: the web server calls `warm_up` (`:115-126`), the CLI builds an `AgentRunner` through it.

## See
`weebot/application/di/__init__.py`
