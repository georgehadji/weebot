---
type: process
name: model cascade
code: CascadeExecutor.call_with_cascade
cluster: application
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
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

**Input:** the executor's message list and the step description, once per tool-loop turn (`weebot/application/agents/executor/_turn.py:54-56`) and once for the budget-cap summary (`weebot/application/agents/executor/_base.py:591-593`).
**Movement:** pick a role cascade from `ROLE_MODEL_CONFIG`, add the pinned model and the step's category model, filter by OpenRouter credit and the session cost limit, hedge probes one at a time, fall back sequentially, then try a live rescue on all-404.
**Output:** one `LLMResponse`, a `CascadeDecision` per attempt, an `LLMCallCompleted` domain event per success; or `AllModelsTrippedError` (or `SessionBudgetExceededError` before any attempt, once the session's hard cost limit is reached, `_cascade.py:538-547`).

## Steps
1. **Construction.** Each `ExecutorAgent` builds its own `CascadeExecutor` with `agent_role=agent_role or "executor"`, `model_provider=self._resolve_model_for_step`, the DI `llm_pool`, `provider_account`, `pinned_model` and `cost_meter`, `on_success` = the context compressor's usage tracker, and `on_call_completed=self._publish_llm_call` (`_base.py:169-188`). Pool, account and cost meter come from `weebot/application/di/__init__.py:501-502, 508`; the pinned model from `StepExecutionContext` (`weebot/application/models/step_execution_context.py:31`; `di/__init__.py:513`).
2. **Role cascade.** `get_model_cascade_for_role(self._agent_role)` (`weebot/application/agents/executor/_cascade.py:552`; `weebot/config/model_refs.py:143-160`): the role's list in `ROLE_MODEL_CONFIG` (`model_refs.py:102-135`), or `_DEFAULT_ROLE_CASCADE` for None or an unknown role (`model_refs.py:137, 149-153`). An Ollama model for the role goes first when enabled, then a free-tier model when WEEBOT_FREE_ROLES lists the role (`model_refs.py:154-155, 172-196`; `weebot/config/free_models.py`), then the user's UI pick from `role_overrides` (`model_refs.py:157-160`). Primary, fallback 1 and fallback 2 default to `MODEL_CASCADE_TIER2` / `TIER3` when the list is short (`_cascade.py:553-555`). The tier constants are at `model_refs.py:31-41`, the premium set at `model_refs.py:140`.
3. **Step model.** `model_provider(description)` (`_cascade.py:558-565`): a screenshot in the buffer forces `[MODEL_VISION_PRIMARY]` once (`_base.py:332-347`); with `WEEBOT_ENABLE_ACR` (on by default) it returns the top two of the shared `AdaptiveCapabilityRouter`'s ranking (DI key `ACR_ROUTER`, `di/__init__.py:349-363`), whose stored posteriors are loaded before routing (`_cascade.py:549-550`) and updated from every call's outcome (`weebot/application/services/routing/adaptive_capability_router.py:231`); otherwise `[model_for_step(description)]` (`_base.py:349-376`), which is the first model of the role mapped to the step's `TaskCategory` (`weebot/application/services/task_model_router.py:22-36, 185-188`; classifier `weebot/application/services/task_model_router.py:150-182`). That lookup reads `ROLE_MODEL_CONFIG` directly, so Ollama and UI overrides do not apply to it. The category is also classified for telemetry, cached per description for the process (`_cascade.py:85, 126-144, 567`).
4. **Credit filter and budget.** Candidates are the pinned model, role primary, ACR list, task model and fallback 1, deduplicated (`_cascade.py:597-603`). With an OpenRouter balance below `OPENROUTER_MIN_CREDIT_USD` (default 0.10), OpenRouter-only models are dropped; unknown balance filters nothing (`_cascade.py:188-217`, threshold `_cascade.py:65-83`; direct-provider prefixes `_cascade.py:184`). Past the session's soft cost limit PREMIUM models are dropped unless that would empty the list (`_cascade.py:505-517`, called at `_cascade.py:604`).
5. **Phase 1, hedged probes.** One probe starts (90 s); the next starts when it fails or after `_HEDGE_DELAY_S` = 20 s (`_cascade.py:67, 608-648`). The loop waits for a probe that succeeds, not the first to finish (`_cascade.py:651-663`). All still-pending probes are cancelled on every exit, with a 5 s bound (`_cascade.py:664-679`), and each cancelled probe that had sent its request is billed as an estimate (one still queued for an `llm_pool` slot sent nothing and is not billed) (prompt tokens only, `LLMCallCompleted.estimated`) by `_call_unanswered` (`_cascade.py:274-281`), because a cancelled non-streamed request still bills. Each attempt holds an `llm_pool` slot before its clock starts (`_cascade.py:310-351`) and calls `llm.chat` with `tools=self._tools.to_params()` (`_cascade.py:394-407`), so per-step tool scoping applies.
6. **Per-attempt bookkeeping.** Success resets the model's breaker, records a SUCCESS decision with a cost estimate and awaits `_call_completed` (`_cascade.py:408-437`); the success path reads `cached_tokens` from the usage and prices them at `CACHE_READ_FRACTION` of the input rate; an empty answer records FAILED (`_cascade.py:439-449`); a timeout records FAILED, counts toward the breaker like any failure and is billed as an estimate (`_cascade.py:450-463`); other errors record `first_error`, count toward the breaker (trips at 5, `_cascade.py:70, 153-163, 475-478`) and mark 5xx models to skip for the rest of the run (`_cascade.py:480-484`). A fast-fail error (`ErrorClassifier.should_fail_fast`: auth, bad request) skips the model for the run, without the breaker or `first_error` (`_cascade.py:465-474`). The shared `fast_fail` flag is set when any `first_error` text matches `_is_fast_fail_error` (`_cascade.py:294-308, 588-593`); it cuts the remaining timeouts to 15 s (`_cascade.py:383`).
7. **Phase 2, sequential.** Fallback 2 then `MODEL_CASCADE_TIER4`, 60 s each, skipping tripped, already-probed and 5xx models (`_cascade.py:687-700`); both phases drop free tiers that train on prompts once the session is tainted (`keep_private`, `weebot/application/agents/executor/_session_scope.py:167`).
8. **Live rescue.** Only when `fast_fail` was set and every recorded first error mentions 404 / not found (`_cascade.py:703-715`): `_live_model_rescue` lists models from the provider account, keeps tool-capable ones allowed by `claude_model_allowed`, prefers paid over `:free`, ranks by context of at least 128k, then catalog price, then context, and tries the first under the pool with a 30 s timeout (`_cascade.py:724-799`).
9. **Terminal.** Otherwise `AllModelsTrippedError(ALL_MODELS_TRIPPED_MESSAGE)` (`_cascade.py:718-720`); the message (`_cascade.py:42-46`) names the API key, the model names and the account credits, and its first sentence is what `_all_models_tripped` matches to skip a replan (`weebot/application/flows/states/_step_outcome.py:164-176`). The executor turns `LLMCapacityExhaustedError` from the pool into an `ErrorEvent` and a message (`_turn.py:57-75`).
10. **Usage reporting.** `_call_completed` builds `LLMCallCompleted(model, tokens, cost=_estimate_cost(...))` (`_cascade.py:245-272`); `_publish_llm_call` stamps the session id and publishes it as a domain event (`_base.py:314-319`). `on_success` feeds the context compressor (`_base.py:184`). After the step, `ExecuteStepHandler` returns `executor.token_usage` (`weebot/application/cqrs/handlers/execute_step_handler.py:37-41, 158`), which the flow adds up in `record_step_usage` (`weebot/application/flows/states/_step_run.py:89`; `weebot/application/flows/plan_act_flow.py:616-620`).

Consequences (read from source, not run):
- The `model` the flow sends with `ExecuteStepCommand` (`--model` or `MODEL_BUDGET`, `_step_run.py:75`) is stored on the executor (`_base.py:115`) and used by the context compressor (`_context_compressor.py:38`). The cascade sees only the flow's own model, and only when set: `pinned_model=self._model or None` (`plan_act_flow.py:605-614`), tried first (`_cascade.py:600`).
- On the `flow run` path no profile is set (`weebot/interfaces/factories.py:228`; `weebot/application/flows/flow_builder.py:95`), so `agent_role` is None and `ExecutorAgent` substitutes `"executor"` (`_base.py:173`): steps use `ROLE_MODEL_CONFIG["executor"]` (`model_refs.py:112`), not `_DEFAULT_ROLE_CASCADE`.
- Fast-fail errors are written to the tracker as FAILED even though they skip the breaker (`_cascade.py:465-474, 486-494`).
- Probe and fallback tiers are labelled per model by `_tier_of`: `:free` is FREE, `PREMIUM_MODELS` is PREMIUM, else BUDGET (`_cascade.py:497-503, 623, 696`). Telemetry only.
- The `fast_fail` flag never comes from the fail-fast branch, which skips `first_error` (`_cascade.py:465-474, 588-593`), so an auth failure alone does not shorten later timeouts.

## If you change this
**Hits:** every executor LLM call (all flows that run steps), `ModelCascadeTracker` / ACR telemetry, cost accounting through `LLMCallCompleted`; `ROLE_MODEL_CONFIG` is shared with DI's per-role LLMs, the context switcher and the role selector (`model_refs.py:72-75`); tests `tests/unit/test_cascade_executor.py`, `tests/unit/test_model_cascade_tracker.py`.
**Does not hit:** the planner's model choice (`PlannerAgent`, through `CreatePlanCommand.model`, `weebot/application/flows/states/planning.py:247`); `weebot/core/model_cascade_config.py`, which only supplies `estimate_cost` (`_cascade.py:14` imports it as `_estimate_cost`).

## See
`weebot/application/agents/executor/_cascade.py`, `weebot/config/model_refs.py`, `weebot/application/services/task_model_router.py`
