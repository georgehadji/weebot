---
type: process
name: model cascade
code: CascadeExecutor.call_with_cascade
cluster: application
universe: live
status: verified
verified: 2026-10-23
commit: c2f39937
consumes:
  - ../objects/application/ExecutorAgent.md
  - ../objects/application/CascadeExecutor.md
  - ../objects/core/ModelCascadeConfig.md
  - ../objects/infrastructure/LLMAdapters.md
  - ../objects/tools/BaseTool.md
produces:
  - ../objects/domain/Event.md
---

# model cascade

**Input:** the executor's message list and the step description, once per tool-loop iteration (`weebot/application/agents/executor/_base.py:734-736`).
**Movement:** pick a role cascade from `ROLE_MODEL_CONFIG`, add the step's category model, filter by OpenRouter credit, hedge probes one at a time, fall back sequentially, then try a live rescue on all-404.
**Output:** one `LLMResponse`, a `CascadeDecision` per attempt, an `LLMCallCompleted` domain event per success; or `AllModelsTrippedError`.

## Steps
1. **Construction.** Each `ExecutorAgent` builds its own `CascadeExecutor` with `agent_role`, `model_provider=self._resolve_model_for_step`, the DI `llm_pool` and `provider_account`, `on_success` = the context compressor's usage tracker, and `on_call_completed=self._publish_llm_call` (`_base.py:302-317`; pool and account from `weebot/application/di/__init__.py:459-460`).
2. **Role cascade.** `get_model_cascade_for_role(self._agent_role)` (`weebot/application/agents/executor/_cascade.py:446`; `weebot/config/model_refs.py:137-145`): the role's list in `ROLE_MODEL_CONFIG` (`model_refs.py:100-129`), or `_DEFAULT_ROLE_CASCADE` for None or an unknown role (`:131, 145`). Primary, fallback 1 and fallback 2 default to `MODEL_CASCADE_TIER2` / `TIER3` when the list is short (`_cascade.py:447-449`).
3. **Step model.** `model_provider(description)` (`_cascade.py:452-458`): a screenshot in the buffer forces `[MODEL_VISION_PRIMARY]` once (`_base.py:408-412`); `WEEBOT_ENABLE_ACR` returns the `AdaptiveCapabilityRouter`'s ordered list; otherwise `[model_for_step(description)]` (`_base.py:426-440`), which is the first model of the role mapped to the step's `TaskCategory` (`weebot/application/services/task_model_router.py:34-48, 162-200`). The category is also classified for telemetry, cached per description for the process (`_cascade.py:103-123, 461`).
4. **Credit filter.** Candidates are role primary, ACR list, task model, fallback 1, deduplicated (`_cascade.py:483-485`). With an OpenRouter balance below `OPENROUTER_MIN_CREDIT_USD` (default 0.10), OpenRouter-only models are dropped; unknown balance filters nothing (`:160-189`, threshold `:54-68`).
5. **Phase 1, hedged probes.** One probe starts; the next starts when it fails or after `_HEDGE_DELAY_S` = 20 s (`_cascade.py:56, 494-541`). The loop waits for a probe that succeeds, not the first to finish (`:524-546`). All still-pending probes are cancelled on every exit, with a 5 s bound (`:547-553`). Each attempt holds an `llm_pool` slot before its clock starts (`:264-303`) and calls `llm.chat` with `tools=self._tools.to_params()` (`:338-347`), so per-step tool scoping applies.
6. **Per-attempt bookkeeping.** Success resets the model's breaker, records a SUCCESS decision with a cost estimate and awaits `_call_completed` (`_cascade.py:349-376`); empty or timeout records FAILED (`:377-400`); other errors count toward the breaker (trips at 5, `:126-135, 412`) and mark 5xx models to skip for the rest of the run (`:414-418`). A fast-fail error (`_is_fast_fail_error`, `:247-262`) cuts the remaining timeouts to 15 s (`:467-480, 334`).
7. **Phase 2, sequential.** Fallback 2 then `MODEL_CASCADE_TIER4`, 60 s each, skipping tripped, already-probed and 5xx models (`_cascade.py:560-575`).
8. **Live rescue.** Only when fast-fail was seen and every recorded first error mentions 404 / not found (`_cascade.py:577-590`): `_live_model_rescue` lists models from the provider account, keeps tool-capable ones allowed by `claude_model_allowed`, prefers paid over `:free`, sorts by context length and tries the first (`:602-665`).
9. **Terminal.** Otherwise `AllModelsTrippedError` (`_cascade.py:592-598`). The executor turns `LLMCapacityExhaustedError` from the pool into an `ErrorEvent` (`_base.py:737-745`).
10. **Usage reporting.** `_call_completed` builds `LLMCallCompleted(model, tokens, cost=_estimate_cost(...))` (`_cascade.py:217-235`); `_publish_llm_call` stamps the session id and publishes it as a domain event (`_base.py:380-385`). `on_success` feeds the context compressor (`_base.py:314`). After the step, `ExecuteStepHandler` returns `executor.token_usage` (`weebot/application/cqrs/handlers/execute_step_handler.py:37-40, 145-155`), which the flow adds up in `record_step_usage` (`weebot/application/flows/plan_act_flow.py:941-945`).

Consequences (read from source, not run):
- The `model` the flow sends with `ExecuteStepCommand` (`--model` or `MODEL_BUDGET`) is stored on the executor (`_base.py:249`) and used by the context compressor, but not by this cascade (step 2-4 inputs only).
- On the `flow run` path no profile is set, so `agent_role` is None (`weebot/interfaces/factories.py:286`) and steps use `_DEFAULT_ROLE_CASCADE`, not `ROLE_MODEL_CONFIG["executor"]` (`model_refs.py:110, 131`).
- Fast-fail errors (auth, bad request) record no decision and do not count toward the breaker, though the comment says they are "recorded as FAILED" (`_cascade.py:401-408`).
- Every Phase 1 probe is labelled `CascadeTier.FREE` (`:501`); in Phase 2 a lone TIER4 model is labelled BUDGET (`:569-570`). Telemetry only.
- The rescue chooses by context length, not price (`:635-637`), so it may pick a premium model.

## If you change this
**Hits:** every executor LLM call (all flows that run steps), `ModelCascadeTracker` / ACR telemetry, cost accounting through `LLMCallCompleted`; tests `tests/unit/test_cascade_executor.py`, `tests/unit/test_model_cascade_tracker.py`.
**Does not hit:** the planner's model choice (`PlannerAgent`, through `CreatePlanCommand.model`); DI's per-role LLM adapters; `weebot/core/model_cascade_config.py`, which only supplies `estimate_cost` (`_cascade.py` imports it as `_estimate_cost`).

## See
`weebot/application/agents/executor/_cascade.py`, `weebot/config/model_refs.py`, `weebot/application/services/task_model_router.py`
