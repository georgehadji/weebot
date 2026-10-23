---
type: object
name: Model cascade config (model_cascade_config.py)
code: select_model_by_tokens, estimate_cost, LONG_CONTEXT_TOKENS
cluster: core
universe: live
status: verified
verified: 2026-10-23
commit: W6.1 (uncommitted at writing)
---

# Model cascade config

Two helpers over other modules' facts: a cost estimate from the generated catalog and a context-size model switch from `model_refs.TASK_MODEL_CASCADE`. It owns no model ids and no prices.

## Why this shape
It began as the cascade's configuration, a hand-written table of models per task with prices. The execution logic moved to `CascadeExecutor` and the role lists to `weebot/config/model_refs.py`, and the table was left behind as a third copy of model facts that had drifted from the catalog. W6.1 (2026-10-23, F18-F20) deleted the table and its `ModelConfig` dataclass: prices come from the catalog, ids from `model_refs`.

## Shape
- `select_model_by_tokens(task_type, estimated_tokens) -> str`: the first id of `TASK_MODEL_CASCADE["long_context"]` at or past `LONG_CONTEXT_TOKENS` (50,000), else of the task's cascade, else of `coding`.
- `estimate_cost(model_id, prompt_tokens, completion_tokens) -> float`: `get_model_config(model_id).estimate_cost(...)`, routing suffixes (`:thinking`, `:free`) stripped by the lookup; 0.0 and a debug log for a model the catalog does not list.

Who reads it (grep, 2026-10-23):
- `estimate_cost`: `application/agents/executor/_cascade.py:14` (the only thing `CascadeExecutor` takes from this file).
- `select_model_by_tokens`: `application/services/context_switcher.py:15, 60`.
- Tests: `tests/unit/fixes/test_w61_model_ssot.py`, `tests/unit/agents/test_w5_cascade_accounting.py`.

## Connected to
- **Feeds:** `CascadeExecutor` (cost number only), `ContextSwitcher`.
- **Reads:** `weebot/config/model_refs.py` (`TASK_MODEL_CASCADE`), `weebot/config/model_registry.py` (catalog lookup).
- **Looks like but is not:** the class `ModelConfig` in `weebot/domain/models/model_config.py:22`, now the only class of that name; `CascadeExecutor` (the execution logic).

## If you change this
**Hits:** cascade cost accounting, the context switcher's model choice.
**Does not hit:** which models anything routes to (edit `model_refs.py`), or prices (regenerate the catalog: `python scripts/generate_catalog.py --write`).

## Surfaces
None directly.

## See
`weebot/core/model_cascade_config.py`
