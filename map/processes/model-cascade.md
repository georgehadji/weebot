---
type: process
name: model cascade
code: CascadeExecutor.call_with_cascade
cluster: application
universe: live
status: verified
verified: 2026-10-27
commit: 4221bd7a
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

**Input:** the executor's message list and the step description, once per tool-loop turn (`weebot/application/agents/executor/_turn.py:54-56`) and once for the budget-cap summary (`weebot/application/agents/executor/_base.py:658-660`).
**Movement:** pick a role cascade from `ROLE_MODEL_CONFIG`, add the pinned model and the step's category model, filter by OpenRouter credit and the session cost limit, hedge probes one at a time, fall back sequentially, then try a live rescue on all-404.
**Output:** one `LLMResponse`, a `CascadeDecision` per attempt, an `LLMCallCompleted` domain event per success; or `AllModelsTrippedError`.

## Steps
1. **Construction.** Each `ExecutorAgent` builds its own `CascadeExecutor` with `agent_role=agent_role or "executor"`, `model_provider=self._resolve_model_for_step`, the DI `llm_pool`, `provider_account`, `pinned_model` and `cost_meter`, `on_success` = the context compressor's usage tracker, and `on_call_completed=self._publish_llm_call` (`_base.py:245-263`). Pool, account and cost meter come from `weebot/application/di/__init__.py:476-477, 483`; the pinned model from `StepExecutionContext` (`weebot/application/models/step_execution_context.py:31-39`; `di/__init__.py:486-487`).
2. **Role cascade.** `get_model_cascade_for_role(self._agent_role)` (`weebot/application/agents/executor/_cascade.py:504-509`; `weebot/config/model_refs.py:143-160`): the role's list in `ROLE_MODEL_CONFIG` (`model_refs.py:102-135`), or `_DEFAULT_ROLE_CASCADE` for None or an unknown role (`:137, 149-153`). An Ollama model for the role goes first when enabled (`:154-155, 163-175`), then the user's UI pick from `role_overrides` (`:157-160`). Primary, fallback 1 and fallback 2 default to `MODEL_CASCADE_TIER2` / `TIER3` when the list is short (`_cascade.py:507-509`). The tier constants are at `model_refs.py:31-41`, the premium set at `:140`.
3. **Step model.** `model_provider(description)` (`_cascade.py:511-518`): a screenshot in the buffer forces `[MODEL_VISION_PRIMARY]` once (`_base.py:417-421`); `WEEBOT_ENABLE_ACR` returns the `AdaptiveCapabilityRouter`'s ordered list; otherwise `[model_for_step(description)]` (`_base.py:424-449`), which is the first model of the role mapped to the step's `TaskCategory` (`weebot/application/services/task_model_router.py:22-36, 185-188`; classifier `:150-182`). That lookup reads `ROLE_MODEL_CONFIG` directly, so Ollama and UI overrides do not apply to it. The category is also classified for telemetry, cached per description for the process (`_cascade.py:82, 122-142, 506`).
4. **Credit filter and budget.** Candidates are the pinned model, role primary, ACR list, task model and fallback 1, deduplicated (`_cascade.py:543-549`). With an OpenRouter balance below `OPENROUTER_MIN_CREDIT_USD` (default 0.10), OpenRouter-only models are dropped; unknown balance filters nothing (`:172-201`, threshold `:53-71`; direct-provider prefixes `:168`). Past the session's soft cost limit PREMIUM models are dropped unless that would empty the list (`:461-473`, called at `:535`).
5. **Phase 1, hedged probes.** One probe starts (90 s); the next starts when it fails or after `_HEDGE_DELAY_S` = 20 s (`_cascade.py:66, 552-566, 574-589`). The loop waits for a probe that succeeds, not the first to finish (`:553-589`). All still-pending probes are cancelled on every exit, with a 5 s bound (`:590-603`). Each attempt holds an `llm_pool` slot before its clock starts (`:276-315`) and calls `llm.chat` with `tools=self._tools.to_params()` (`:354-366`), so per-step tool scoping applies.
6. **Per-attempt bookkeeping.** Success resets the model's breaker, records a SUCCESS decision with a cost estimate and awaits `_call_completed` (`_cascade.py:383-410`); empty or timeout records FAILED (`:397-419`); other errors record `first_error`, count toward the breaker (trips at 5, `:137-146, 432-434`) and mark 5xx models to skip for the rest of the run (`:436-440`). A fast-fail error (`ErrorClassifier.should_fail_fast`: auth, bad request) skips the model for the run, without the breaker or `first_error` (`:421-430`). The shared `fast_fail` flag is set when any `first_error` text matches `_is_fast_fail_error` (`:259-274, 519-524`); it cuts the remaining timeouts to 15 s (`:346`).
7. **Phase 2, sequential.** Fallback 2 then `MODEL_CASCADE_TIER4`, 60 s each, skipping tripped, already-probed and 5xx models (`_cascade.py:625-639`).
8. **Live rescue.** Only when `fast_fail` was set and every recorded first error mentions 404 / not found (`_cascade.py:641-654`): `_live_model_rescue` lists models from the provider account, keeps tool-capable ones allowed by `claude_model_allowed`, prefers paid over `:free`, ranks by context of at least 128k, then catalog price, then context, and tries the first under the pool with a 30 s timeout (`:651-720`).
9. **Terminal.** Otherwise `AllModelsTrippedError(ALL_MODELS_TRIPPED_MESSAGE)` (`_cascade.py:656-659`); the message (`_cascade.py:41-45`) names the API key, the model names and the account credits, and its first sentence is what `ExecutingState` matches to skip a replan. The executor turns `LLMCapacityExhaustedError` from the pool into an `ErrorEvent` and a message (`_turn.py:57-75`).
10. **Usage reporting.** `_call_completed` builds `LLMCallCompleted(model, tokens, cost=_estimate_cost(...))` (`_cascade.py:243-261`); `_publish_llm_call` stamps the session id and publishes it as a domain event (`_base.py:389-394`). `on_success` feeds the context compressor (`_base.py:260`). After the step, `ExecuteStepHandler` returns `executor.token_usage` (`weebot/application/cqrs/handlers/execute_step_handler.py:37-40, 153`), which the flow adds up in `record_step_usage` (`weebot/application/flows/states/_step_run.py:88`; `weebot/application/flows/plan_act_flow.py:732-736`).

Consequences (read from source, not run):
- The `model` the flow sends with `ExecuteStepCommand` (`--model` or `MODEL_BUDGET`, `_step_run.py:74`) is stored on the executor (`_base.py:192`) and used by the context compressor. The cascade sees only the flow's own model, and only when set: `pinned_model=self._model or None` (`plan_act_flow.py:728`), tried first (`_cascade.py:546`).
- On the `flow run` path no profile is set (`weebot/interfaces/factories.py:226`; `weebot/application/flows/flow_builder.py:138`), so `agent_role` is None and `ExecutorAgent` substitutes `"executor"` (`_base.py:249`): steps use `ROLE_MODEL_CONFIG["executor"]` (`model_refs.py:112`), not `_DEFAULT_ROLE_CASCADE`.
- Fast-fail errors are written to the tracker as FAILED even though they skip the breaker (`_cascade.py:444, 455-463`).
- Probe and fallback tiers are labelled per model by `_tier_of`: `:free` is FREE, `PREMIUM_MODELS` is PREMIUM, else BUDGET (`:452-459, 551, 620`). Telemetry only.
- The `fast_fail` flag never comes from the fail-fast branch, which skips `first_error` (`:421-434, 519-521`), so an auth failure alone does not shorten later timeouts.

## If you change this
**Hits:** every executor LLM call (all flows that run steps), `ModelCascadeTracker` / ACR telemetry, cost accounting through `LLMCallCompleted`; `ROLE_MODEL_CONFIG` is shared with DI's per-role LLMs, the context switcher and the role selector (`model_refs.py:72-75`); tests `tests/unit/test_cascade_executor.py`, `tests/unit/test_model_cascade_tracker.py`.
**Does not hit:** the planner's model choice (`PlannerAgent`, through `CreatePlanCommand.model`, `weebot/application/flows/states/planning.py:223`); `weebot/core/model_cascade_config.py`, which only supplies `estimate_cost` (`_cascade.py:14` imports it as `_estimate_cost`).

## See
`weebot/application/agents/executor/_cascade.py`, `weebot/config/model_refs.py`, `weebot/application/services/task_model_router.py`
