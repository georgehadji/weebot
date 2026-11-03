# ADR-021: Loop detectors compose behind one config

**Date:** 2026-11-03
**Status:** Implemented 2026-11-03 (plan H11, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "Proceed". The plan marks H11 eval-gated; the before and after numbers are not collected yet.
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

`IterationGuard` caught two things: the same tool signature four times running, and the same assistant text twice. A model that alternated two calls (A-B-A-B), re-read an unchanged file, or answered with an empty message burned its step budget with nothing to stop it. The guard's limits were also written twice, in `_iteration_guard.py` and as literals in `_base.py`.

## Decision

1. **`GuardConfig`**, a frozen dataclass in `executor/_loop_detectors.py`, holds every number. `ExecutorAgent` takes it as `guard_config` (default `GuardConfig()`) and passes it to `IterationGuard` and `ToolBatchRunner`. The literals in `_base.py` are gone. `record_iteration` is now `record_loop_turn`: it counts loop passes, not tool calls.
2. **Five detectors**, each with its own state and an `observe` that never raises:

   | Detector | Rule | Outcome |
   |---|---|---|
   | `CycleDetector` | the signature sequence repeats with period 2, 3 or 4 | first match a note to the model, a later match stops the step |
   | `DuplicateResultStub` | the result's sha256 equals an earlier successful result's (min 200 chars) | the model gets `[identical to result of call #k]`; the UI event keeps the text |
   | `EmptyResponseBudget` | an empty reply, while wasted spend is under `min(0.5 x step cost, $0.02)` and at most 2 retries | the empty message is dropped and a user-role nudge is added; otherwise the existing "No result" path runs |
   | `RepetitionGuard` | 5-gram Jaccard of the assistant text against the last 2 turns is at least 0.85 | a note |
   | `WallClockWrapUp` | 80% of the step's wall-clock budget is used | one wrap-up note, in a user-role message |

3. **Notes go where they cannot break pairing.** Cycle and repetition notes join the batch's recovery hints, which follow the tool messages. The wrap-up note is a user message at the top of a loop pass, never the system prompt, so the prompt prefix stays stable for caching (H10).
4. **The plan's single `observe(GuardEvent)` was not built.** The detectors watch different things (a signature, a result, a cost, a text, a clock). Each has a typed `observe` instead of one event union.

## Consequences

- A cycle of tool calls ends within a call or two of its second repetition instead of the step budget.
- The empty-reply retry is inert without a cost meter (the budget is zero), so behaviour there is unchanged.
- `wall_clock_budget_s` (600 s) is a new number: no step wall-clock budget existed. Nothing enforces it; only the note uses it.
- A stubbed result points at an earlier call that context compression may since have removed.
- Eval gate still open: iterations per solved step must not rise and wasted-iteration share must fall.
