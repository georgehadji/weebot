---
type: object
name: CascadeExecutor
code: CascadeExecutor
cluster: application
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# CascadeExecutor

Makes one LLM call for `ExecutorAgent` by trying several models in a fixed order until one answers, with per-model circuit breakers, optional concurrency pooling and an OpenRouter credit pre-check. `call_with_cascade(messages, description)` returns an `LLMResponse` or raises `AllModelsTrippedError`.

## Why this shape
Cost and availability: try cheap or probable models first, spend more only on failure. Extracted from the old executor so LLM-calling logic is separate from step orchestration (`weebot/application/agents/executor/_cascade.py:1-6`). Several comments in the file record bugs that shaped it (probes billed but discarded, pool slot taken inside the timeout, rescue call outside the pool); keep those behaviours when editing.

## Shape
`call_with_cascade` at `_cascade.py:521`. Candidate models come from `get_model_cascade_for_role(agent_role)` plus the model provider's choice for the step (`_cascade.py:552-566`).

1. **Credit filter** (`_cascade.py:597-607`): candidates = pinned model (`flow run --model`), role primary, ACR list, task model, role fallback 1, de-duplicated, then dropped past the soft cost limit if PREMIUM (`_within_budget`, `_cascade.py:505-518`). If remaining OpenRouter credit is under `OPENROUTER_MIN_CREDIT_USD` (default 0.10 USD) OpenRouter-only models are dropped; unknown credit means no filtering (`_cascade.py:62-83, 188-217`).
2. **Phase 1, hedged probes** (`_cascade.py:608-685`): one candidate runs with a 90 s timeout; the next starts when it fails or after `_HEDGE_DELAY_S` (20 s) without an answer. Waits for the first *success* (not first finish), then cancels the rest in a `finally`, bills a cancelled probe that had sent its request, and gives the cancellations 5 s to land (`_cascade.py:648-679`). Costs: a cancelled non-streamed request still bills, which is why probes are no longer all started at once.
3. **Phase 2, sequential** (`_cascade.py:686-700`): role fallback 2, then `MODEL_CASCADE_TIER4`, each 60 s, skipping tripped, already-probed and server-error models. The `_TIER3_MODEL` constant is only the default when a role cascade has fewer than three entries (`_cascade.py:555`), so the method's docstring ("tier3 → tier4", `_cascade.py:524`) is not literally what runs.
4. **Live rescue** (`_cascade.py:702-715`): only if fast-fail was detected and every first error was a 404 / not-found. Picks, among paid tool-capable models (free only if no paid), the cheapest catalog-priced one with at least 128k context, unpriced last, and calls it inside the LLM pool with a 30 s timeout (`_cascade.py:724-799`, ranking `_cascade.py:762-766`).
5. Otherwise raises `AllModelsTrippedError` (`_cascade.py:717-720`).

Per-attempt rules (`_cascade_try_chat_unpooled`, `_cascade.py:353-494`): a tripped model is skipped and recorded CIRCUIT_OPEN; 401/403/404-class errors (`ErrorClassifier.should_fail_fast`) are suppressed, do **not** count toward the breaker and exclude the model for the rest of the run; other errors bump the breaker and server errors also exclude the model; success resets the breaker and records latency, tokens and estimated cost. Once a fast-fail error is seen, remaining timeouts shrink to 15 s (`_cascade.py:383, 585-593`).

Breaker numbers: logged at 3 failures (`_cascade.py:71`), tripped at 5 (`_cascade.py:70`).

Billing rules: cached prompt tokens are priced at the cache rate; a timed-out probe, or a cancelled one that had sent its request, is billed as an estimate (prompt tokens only, flagged `estimated`) and a timeout counts toward the breaker; before each call `call_with_cascade` raises `SessionBudgetExceededError` once the session's hard limit (or its granted allowance) is reached.

Pool: `_cascade_try_chat` takes a pool slot *before* the latency clock and outside `wait_for`; `LLMCapacityExhaustedError` propagates and stops the cascade (`_cascade.py:310-351`).

## Connected to
- **Owned by** `ExecutorAgent` (`_base.py:169-188`), which passes `model_provider=self._resolve_model_for_step`, `llm_pool`, `provider_account`, and `on_success` = the context compressor's token tracker.
- **Telemetry:** `ModelCascadeTracker` and optional ACR router record every `CascadeDecision` (`_cascade.py:219-243`). The tracker is an in-memory ring buffer owned by each `ExecutorAgent` (`_base.py:185`); the DI `"cascade_tracker"` binding is not passed to executors, and the Mediator path builds an executor per step, so nothing aggregates decisions across steps (see Event store card, cost views); the cost estimate feeds the number `mcp/resources.py` publishes (`_cascade.py:429-431`, published at `weebot/mcp/resources.py:273`).
- **Config:** tier constants and the one role table (`ROLE_MODEL_CONFIG`, read through `get_model_cascade_for_role`) come from `weebot/config/model_refs.py` (`_cascade.py:25, 57-59, 552`). `weebot/core/model_cascade_config.py` supplies only `estimate_cost` (`_cascade.py:14`), read from the catalog (see its card).
- **Looks like but is not:** the adapter-level resilience in `weebot/infrastructure/adapters/llm/` (retries, its own breakers); this cascade sits above it.

## If you change this
**Hits:** `ExecutorAgent` (only caller of `call_with_cascade` in `weebot/` and `cli/`: `_base.py:591`, `weebot/application/agents/executor/_turn.py:54`); LLM spend and latency (Phase 1 bills all probes); the exceptions `ExecutorAgent` catches (`AllModelsTrippedError`, `LLMCapacityExhaustedError`); the tracker and any cost report built on it; tests `tests/integration/test_cascade_integration.py`, `tests/unit/agents/test_cascade_does_not_bill_orphans.py`, `tests/unit/agents/test_w5_cascade_accounting.py`, `tests/unit/application/test_bulkheads.py`, `tests/unit/adapters/test_retry_amplification.py`, `tests/unit/test_architecture_fitness.py`.
**Does not hit:** plan creation (`PlannerAgent` calls the LLM directly, no cascade); tool execution; the flow state machine.

## Surfaces
None directly. Users see it as "All AI models are currently unavailable" messages from the executor.

## See
`weebot/application/agents/executor/_cascade.py`
