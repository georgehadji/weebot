---
type: object
name: PlannerAgent
code: PlannerAgent
cluster: application
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# PlannerAgent

Turns a user task into a `Plan` (title, message, steps) with one JSON-mode LLM call, and revises a plan after a step completes. It has no tools and does not use the model cascade: it sends one model, the caller's override or else the planner role's first non-free model (`role_primary_model`, `weebot/application/agents/planner.py:100`; audit R17). `create_plan` and `update_plan` are async generators that yield `PlanEvent`s.

## Why this shape
The model returns JSON; everything after that is defensive, because a malformed plan must never stop the flow: parse, retry once, then fall back to a fixed two-step plan (`weebot/application/agents/planner.py:271-279`). Heuristics in `_parse_plan` keep plans executable: at most one step that writes spec files, and steps naming more than 5 discrete items are split into batches (`weebot/application/agents/planner.py:350-359, 361-391`), because long steps made the executor loop.

## Shape
- Constructor builds the system prompt: base prompt file or a `PromptRegistry` variant, plus spec-file rule (only for multi-section UI skills, `planner.py:103-109`), skill prompt, known facts, skill catalog and workflow hints (`planner.py:100-127`). Stored as `_memory[0]`.
- `create_plan(prompt, attachments, meta_notes)` (`planner.py:242`): resets memory to the system prompt, adds attachments and the last 5 meta-analysis notes (`planner.py:250-261`), emits "Creating plan...", calls the LLM through `_chat_json` with `response_format=json_object`, deterministic temperature and `MAX_TOKENS_PLANNING`, inside a 240 s `deadline_scope` so the adapter's retries stop at the deadline (`planner.py:33, 196-209`). Parse failure → `_request_json_retry` once (`planner.py:211-220`) → `_minimal_fallback_plan` plus an `ErrorEvent` (`planner.py:271-279`). Yields `TitleEvent` then `PlanEvent(CREATED)` (`planner.py:282-283`).
- `update_plan(plan, completed_step, failure_context)` (`planner.py:285`): sends the current plan and the completed step; a failure context (first 1000 chars) tells the model not to repeat the blocked approach (`planner.py:291-298`). Result is merged with `plan.merge(...)` and emitted as `PlanEvent(UPDATED)`; any exception yields an `ErrorEvent` and leaves the plan unchanged (`planner.py:309-316`). Uses the update prompt, not `_memory`.
- `_parse_plan` (`planner.py:332-397`): reads `id`, `description`, `acceptance_criteria`, `context_scope` (invalid values fall back to `FULL`, `planner.py:346-349`) and records how many heuristics fired in `Plan.heuristic_splits` (`planner.py:339, 358, 367, 396`). Step ids default to positional `step-N`.
- JSON extraction is the shared `extract_json_text` (`planner.py:169-194`), no longer private.

## Connected to
- **Invoked through the Mediator:** `CreatePlanHandler` builds a `PlannerAgent` and iterates `create_plan` (`cqrs/handlers/create_plan_handler.py:110-114`); `PlanningState` sends `CreatePlanCommand` (`states/planning.py:237`). `UpdatePlanHandler` (`update_plan_handler.py:52, 66`) and `UpdatingState` (`states/updating.py:190`, via `context._planner`) call `update_plan`.
- **Other constructors:** `PlanActFlow` (`weebot/application/flows/_plan_act_wiring.py:233`), `PlanningState` (`states/planning.py:331`), `model_selector.py:42`, `services/context_switcher.py:89`.
- **Produces:** `Plan` / `Step` (domain models), which `ExecutorAgent` consumes; `Step.context_scope` set here controls the executor's prompt.
- **Looks like but is not:** `ExecutorAgent` (runs steps); `PlanCriticService` (scores plans, in `CritiquingState`); `ParallelPlanner` (`application/agents/parallel_planner.py`, not covered).

## If you change this
**Hits:** `Plan`/`Step` shape (the parser reads fixed keys); the planner prompt files and PromptRegistry variants; the five construction sites above; step ids, which are positional and which `FlowRouter` relies on to reset per-step gate acks on re-plan (`flow_router.py:174-181`); tests `tests/unit/agents/test_agents_validate_their_json.py`, `tests/unit/test_cqrs_persistence.py`, `tests/unit/test_plan_template_cache_is_gated.py`, `tests/integration/test_website_generation.py`.
**Does not hit:** model cascade and executor loops; tool registration.

## Surfaces
Plan events are shown to users (plan review, CLI, UI) after the flow emits them.

## See
`weebot/application/agents/planner.py`
