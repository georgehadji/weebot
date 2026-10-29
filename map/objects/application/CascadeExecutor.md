---
type: object
name: CascadeExecutor
code: CascadeExecutor
cluster: application
universe: live
status: verified
verified: 2026-10-29
commit: 83c1f712
---

# CascadeExecutor

Makes one LLM call for `ExecutorAgent` by trying several models in a fixed order until one answers, with per-model circuit breakers, optional concurrency pooling and an OpenRouter credit pre-check. `call_with_cascade(messages, description)` returns an `LLMResponse` or raises `AllModelsTrippedError`.

## Why this shape
Cost and availability: try cheap or probable models first, spend more only on failure. Extracted from the old executor so LLM-calling logic is separate from step orchestration (`weebot/application/agents/executor/_cascade.py:1-6`). Several comments in the file record bugs that shaped it (probes billed but discarded, pool slot taken inside the timeout, rescue call outside the pool); keep those behaviours when editing.

## Shape
`call_with_cascade` at `_cascade.py:521`. Candidate models come from `get_model_cascade_for_role(agent_role)` plus the model provider's choice for the step (`:406-420`).

1. **Credit filter** (`:445-448`): candidates = role primary, ACR list or task model, role fallback 1, de-duplicated. If remaining OpenRouter credit is under `OPENROUTER_MIN_CREDITS` (default 10000) OpenRouter-only models are dropped; unknown credit means no filtering (`:151-180`).
2. **Phase 1, parallel probes** (`:450-509`): all candidates called at once with a 90 s timeout, tier FREE. Waits for the first *success* (not first finish), then cancels and awaits the rest in a `finally` (`:479-504`). Costs: every probe is a billed request.
3. **Phase 2, sequential** (`:511-526`): role fallback 2, then `MODEL_CASCADE_TIER4`, each 60 s, skipping tripped, already-probed and server-error models. The `_TIER3_MODEL` constant is only the default when a role cascade has fewer than three entries (`:411`), so the method's docstring ("tier3 → tier4") is not literally what runs.
4. **Live rescue** (`:528-541`): only if fast-fail was detected and every first error was a 404 / not-found. Picks the paid tool-capable model with the largest context (free only if no paid) and calls it inside the LLM pool with a 30 s timeout (`:553-613`).
5. Otherwise raises `AllModelsTrippedError` (`:546`).

Per-attempt rules (`_cascade_try_chat_unpooled`, `:268-390`): a tripped model is skipped and recorded CIRCUIT_OPEN; 401/403/404-class errors are suppressed and do **not** count toward the breaker; other errors bump the breaker and server errors exclude the model for the rest of the run; success resets the breaker and records latency, tokens and estimated cost. Once a fast-fail error is seen, remaining timeouts shrink to 15 s (`:297, 436-440`).

Breaker numbers: logged at 3 failures (`:126`), tripped at 5 (`:120`).

Billing rules: cached prompt tokens are priced at the cache rate; a timed-out probe, or a cancelled one that had sent its request, is billed as an estimate (prompt tokens only, flagged `estimated`) and a timeout counts toward the breaker; before each call `call_with_cascade` raises `SessionBudgetExceededError` once the session's hard limit (or its granted allowance) is reached.

Pool: `_cascade_try_chat` takes a pool slot *before* the latency clock and outside `wait_for`; `LLMCapacityExhaustedError` propagates and stops the cascade (`:227-266`).

## Connected to
- **Owned by** `ExecutorAgent` (`_base.py:250-269`), which passes `model_provider=self._resolve_model_for_step`, `llm_pool`, `provider_account`, and `on_success` = the context compressor's token tracker.
- **Telemetry:** `ModelCascadeTracker` and optional ACR router record every `CascadeDecision` (`:182-206`). The tracker is an in-memory ring buffer owned by each `ExecutorAgent` (`_base.py:266`); the DI `"cascade_tracker"` binding is not passed to executors, and the Mediator path builds an executor per step, so nothing aggregates decisions across steps (see Event store card, cost views); the cost estimate feeds the number `mcp/resources.py` publishes (comment at `:332-335`).
- **Config:** tier constants and the one role table (`ROLE_MODEL_CONFIG`, read through `get_model_cascade_for_role`) come from `weebot/config/model_refs.py` (`_cascade.py:25, 56-59, 438`). `weebot/core/model_cascade_config.py` supplies only `estimate_cost` (`_cascade.py:14`), read from the catalog (see its card).
- **Looks like but is not:** the adapter-level resilience in `weebot/infrastructure/adapters/llm/` (retries, its own breakers); this cascade sits above it.

## If you change this
**Hits:** `ExecutorAgent` (only caller of `call_with_cascade` in `weebot/` and `cli/`: `_base.py:672`, `weebot/application/agents/executor/_turn.py:54`); LLM spend and latency (Phase 1 bills all probes); the exceptions `ExecutorAgent` catches (`AllModelsTrippedError`, `LLMCapacityExhaustedError`); the tracker and any cost report built on it; tests `tests/integration/test_cascade_integration.py`, `tests/unit/agents/test_cascade_does_not_bill_orphans.py`, `tests/unit/agents/test_w5_cascade_accounting.py`, `tests/unit/application/test_bulkheads.py`, `tests/unit/adapters/test_retry_amplification.py`, `tests/unit/test_architecture_fitness.py`.
**Does not hit:** plan creation (`PlannerAgent` calls the LLM directly, no cascade); tool execution; the flow state machine.

## Surfaces
None directly. Users see it as "All AI models are currently unavailable" messages from the executor.

## See
`weebot/application/agents/executor/_cascade.py`
