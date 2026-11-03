# ADR-016: The request prefix does not change inside a session

**Date:** 2026-11-03
**Status:** Implemented 2026-11-03 (plan H10, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "Proceed". Covers H2 (cache gating by model), H10 and H24a (frozen memory snapshot, ADR-023). The eval that decides D3 is not run (see Consequences).
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

A provider's prompt cache matches a request's prefix byte for byte, in the order tools, system, messages. The executor changed that prefix at every step:

- `build_executor_prompt` put per-step text (retrieved skills, behavioural rules, the output root, the memory snapshot) in the system prompt.
- `_turn._assemble_messages` appended a tool note that depends on the step to the system message.
- `ToolCollection.to_params()` returned the step's tools in registration order.

Nothing checked that a prefix held, so a change could not be seen.

## Decision

1. **`PromptLayout`** (`application/models/prompt_layout.py`) is a frozen value built by `PromptLayoutBuilder`: `system_static` (boot block, base prompt, harness, personality), `system_session` (user profile, frozen memory snapshot), `step_context` (retrieved skills, behavioural rules, output root, tool note) and `prefix_sha`, the sha256 of the system text and the canonical tools.
2. **Wire order.** Tools first, sorted by name with sorted keys (`canonical_tools`, applied in `to_params`). Then `system = system_static + system_session`. `step_context` leads the step's first user message.
3. **The system prompt is built once per session and context scope** (`_step_setup._frozen_system`, bounded to 32 entries). A step with a different context scope (ICM scoping) gets its own entry, so scoping still works and the change is counted.
4. **Tool scope granularity.** `WEEBOT_TOOL_SCOPE_GRANULARITY=step|plan`, default `step`. With `plan` the tool list is the union of the plan's step scopes, chosen once. The "More tools exist" note is in `step_context` in both modes.
5. **`PromptPrefixStore`** (port) with an in-memory LRU adapter (256 sessions) records the system and tool hashes per session at each step and says what changed. The DI container counts changes in `weebot_prompt_prefix_changes_total{reason}` (`system`, `tools`, `both`). A session delete forgets the record.
6. **Breakpoints.** The caching adapter marks the last system message and the last user message before the newest assistant turn (it used the first assistant turn).
7. **Prompt-surface lock.** `scripts/prompt_surface.py` renders `system_static` for each context scope and the canonical tool schemas for each role from fixed inputs. `make lint-prompt-surface` (part of `make check`) fails with a unified diff when they differ from `tasks/quality/prompt_surface.lock` and the text under `tasks/quality/prompt_surface/`. The author re-locks with `--update`, so the change is in the PR diff.
8. `_summarize_on_budget_cap` and `_assemble_messages` send the same system message.

## Consequences

- Inside a step, and across steps under `plan` granularity, the tools and the system text are identical bytes (`tests/unit/application/test_prompt_prefix_invariant.py`).
- Under `step` granularity the tools block still differs between steps whose scopes differ; the metric shows how often. That is the trade D3 asks to decide by eval.
- **Not measured:** cache-read ratio and cost per task under `step` and `plan`, and the 60% target on Claude runs. Both need live runs. Until they are attached, the default stays `step`.
- `step_context` is a user message, so behavioural rules lose the weight of a system instruction. The eval should watch rule compliance.
- The conversation is cleared at every step, so a step's cached prefix is the system text and the tools; the messages restart. The second breakpoint helps the turns inside one step.
- The prompt surface is now part of the diff of every PR that touches the base prompt, the boot block, or a tool's name, description or parameters.
