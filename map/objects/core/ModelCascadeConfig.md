---
type: object
name: Model cascade config (model_cascade_config.py)
code: ModelConfig, MODEL_CASCADE, select_model_by_tokens, estimate_cost
cluster: core
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# Model cascade config

A hand-written table of OpenRouter models per task type (price, context size, timeout, tier) with a few lookup helpers and a cost estimator. It does not drive `CascadeExecutor`; since 2026-10-22 (W1.5) its docstring and root `CLAUDE.md` rule 4 say so. Line numbers below are from `f00ea38`; W1.5 deleted `AGENT_ROLES`, `very_long_context`, the medium-context block, `get_model_for_context_size` and `get_model_stats`.

## Why this shape
It began as the cascade's configuration; the execution logic moved to `CascadeExecutor` and the role-to-model lists moved to `weebot/config/model_refs.py`, leaving this module as a task-type catalogue plus price fallback (`weebot/core/model_cascade_config.py:10-21`, `weebot/config/model_refs.py:798-806`).

## Shape
- `ModelConfig` is a plain dataclass: id, name, tier (free, budget, standard, premium), prices per 1M tokens, context length, timeout, retries, `use_for`, `recommended` (`:37-51`).
- `MODEL_CASCADE`: six task keys (`coding`, `analysis`, `chat`, `planning`, `subagent`, `long_context`), each an ordered list of models (`:58-308`). Prices carry the date 2026-06-09 (`:8`).
- Helpers: `get_models_for_task`, `get_recommended_model` (first `recommended`, else first), `get_cascade_for_task` (sorted free to premium) (`:359-380`); `select_model_by_tokens` with `TOKEN_THRESHOLDS` (`:316-351`).
- `estimate_cost(model_id, prompt_tokens, completion_tokens)` asks the generated catalog first (`weebot/config/model_registry.get_model_config`), then falls back to this table, then returns 0.0 (`:383-403`).

Who reads it (grep, 2026-10-21):
- `estimate_cost`: `application/agents/executor/_cascade.py:14, 335` (the only thing `CascadeExecutor` takes from this file).
- `get_cascade_for_task`: `config/model_refs.py:786`, inside `get_models_for_role_and_task`, which swallows any exception (`:792-793`).
- `select_model_by_tokens`: `application/services/context_switcher.py:15, 60`.
- Tests: `tests/unit/test_routed_models_exist.py:21` (checks every id exists in the catalog), `tests/unit/agents/test_w5_cascade_accounting.py`.

Consequences (read from source, not run):
- `CascadeExecutor` takes its tiers from `model_refs.MODEL_CASCADE_TIER2/3/4` and `get_model_cascade_for_role` (`_cascade.py:24, 46-48, 406`), not from `MODEL_CASCADE`.
- `ROLE_MODEL_CONFIG`, which the `role_model_selector` docstring attributes to this module, is defined in `model_refs.py`.
- `model_refs.get_models_for_role_and_task`, the reader of `get_cascade_for_task`, has no caller itself (grep, 2026-10-22).
- Model ids and prices exist in three places: this table, the role lists in `model_refs.py`, and the generated catalog `weebot/config/model_catalog.py`. `test_routed_models_exist.py` guards that ids exist; nothing guards that prices agree.

## Connected to
- **Feeds:** `CascadeExecutor` (cost number only), `context_switcher`, `model_refs.get_models_for_role_and_task`.
- **Related:** `weebot/config/model_refs.py` (the real tier and role lists), `weebot/config/model_registry.py` and `model_catalog.py` (generated pricing and capabilities).
- **Looks like but is not:** the class `ModelConfig` in `weebot/domain/models/model_config.py:22` (a different class with the same name; the catalog and `get_model_config` use that one); `CascadeExecutor` (the execution logic).

## If you change this
**Hits:** cost accounting fallback (`_cascade.py:335`), `context_switcher` model choice, `get_models_for_role_and_task`, tests `tests/unit/test_routed_models_exist.py`, `tests/unit/agents/test_w5_cascade_accounting.py`.
**Does not hit:** which models `CascadeExecutor` actually tries (edit `model_refs.py` for that).

## Surfaces
None directly. Operators change models by editing this file or `model_refs.py`.

## See
`weebot/core/model_cascade_config.py`
