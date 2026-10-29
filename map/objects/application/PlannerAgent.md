---
type: object
name: PlannerAgent
code: PlannerAgent
cluster: application
universe: live
status: verified
verified: 2026-10-29
commit: bc2fe74e
---

# PlannerAgent

Turns a user task into a `Plan` (title, message, steps) with one JSON-mode LLM call, and revises a plan after a step completes. It has no tools and does not use the model cascade. `create_plan` and `update_plan` are async generators that yield `PlanEvent`s.

## Why this shape
The model returns JSON; everything after that is defensive, because a malformed plan must never stop the flow: parse, retry once, then fall back to a fixed two-step plan (`weebot/application/agents/planner.py:267-275`). Heuristics in `_parse_plan` keep plans executable: at most one step that writes spec files, and steps naming more than 5 discrete items are split into batches (`:314-355, 357-377`), because long steps made the executor loop.

## Shape
- Constructor builds the system prompt: base prompt file or a `PromptRegistry` variant, plus spec-file rule (only for multi-section UI skills, `:103-106`), skill prompt, known facts, skill catalog and workflow hints (`:99-124`). Stored as `_memory[0]`.
- `create_plan(prompt, attachments, meta_notes)` (`:238`): resets memory to the system prompt, adds attachments and the last 5 meta-analysis notes (`:251-257`), emits "Creating plan...", calls the LLM through `_chat_json` with `response_format=json_object`, deterministic temperature and `MAX_TOKENS_PLANNING`, inside a 240 s `deadline_scope` so the adapter's retries stop at the deadline (`:32, 193-205`). Parse failure → `_request_json_retry` once (`:207`) → `_minimal_fallback_plan` plus an `ErrorEvent` (`:270-275`). Yields `TitleEvent` then `PlanEvent(CREATED)` (`:278-279`).
- `update_plan(plan, completed_step, failure_context)` (`:281`): sends the current plan and the completed step; a failure context (first 1000 chars) tells the model not to repeat the blocked approach (`:288-294`). Result is merged with `plan.merge(...)` and emitted as `PlanEvent(UPDATED)`; any exception yields an `ErrorEvent` and leaves the plan unchanged (`:305-312`). Uses the update prompt, not `_memory`.
- `_parse_plan` (`:329`): reads `id`, `description`, `acceptance_criteria`, `context_scope` (invalid values fall back to `FULL`, `:342-345`) and records how many heuristics fired in `_heuristic_splits` (`:391-393`). Step ids default to positional `step-N`.
- JSON extraction is the shared `extract_json_text` (`:167-191`), no longer private.

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
