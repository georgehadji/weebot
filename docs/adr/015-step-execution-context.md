# ADR-015: The executor that runs a step gets the flow's settings

**Date:** 2026-10-23
**Status:** Implemented 2026-10-23 (W5.4, F25). Written and implemented in one pass under the user's instruction "make sure all the plans have been implemented"; the review gate for the decision itself is this file.
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

`ExecutingState` runs every plan step through the mediator: it sends `ExecuteStepCommand`, and `ExecuteStepHandler` builds an `ExecutorAgent` with the container's `_executor_factory` and runs the step on it. The factory is a closure made once, when the container builds the mediator, before any flow exists. So the executor that runs a step has only container singletons (LLM, the container's admin tool set, event bus, state repo, skill retriever, personality, tracing, LLM pool, provider account).

`PlanActFlow` meanwhile builds its own `ExecutorAgent` (`self._executor`) with everything the flow knows: the role-scoped tool collection, skill prompt, profile, agent role, behavioral learner, harness instruction block, middleware chain, trajectory config and step budget. That executor never runs a step. It serves the summarize fallback, and it is where the flow reads token usage and detected skill gaps.

Consequences, read from source on 2026-10-23:
- Steps ran with the container's admin tools, not the flow's role-scoped collection: the handler ignored `ExecuteStepCommand.tools`.
- The skill prompt, role, profile, behavioral rules, harness block, middleware and trajectory config never reached step execution.
- Token-based termination read the idle executor (about 0 tokens), so it could not fire; verification and completion read token usage and skill gaps from it too.

## Decision

1. **`StepExecutionContext`** (`weebot/application/models/step_execution_context.py`), a frozen value object holding the per-flow executor settings: tools, skill prompt, skill retriever, profile name, personality, agent role, behavioral learner, harness instruction block, middleware chain, trajectory config, max steps. `PlanActFlow.step_execution_context()` builds it from the flow's current values, so a harness block resolved mid-run is in the next step's context.
2. **On the command, in process only.** `ExecuteStepCommand.step_context` carries it, `exclude=True` so it never appears in a dump or a persisted payload. The mediator is in process; a command that crossed a process boundary would arrive without it and fall back to the singletons, as before.
3. **The factory overlays it.** `_executor_factory(*, model, session, context=None)` starts from the singletons and applies every non-None context field. The handler's no-factory fallback does the same.
4. **Usage comes back.** The handler's result carries the step executor's `token_usage` and `skill_gaps`. The flow totals the usage across steps (`PlanActFlow.token_usage` adds the summary executor's own) and collects the gaps.
5. **Rename.** `PlanActFlow._executor` becomes `_summary_executor`: the summarize fallback is what it is for.

## Alternatives considered

- **A per-session registry the handler looks up.** Avoids touching the command, but is process-global state keyed by session id, with its own lifetime to manage. The command field is explicit and has the same in-process limit.
- **Make the flow's executor the step executor (bypass the mediator).** Undoes the CQRS step path that W4.x builds on (telemetry, save policy, event store).

## Consequences

- A step now runs with the flow's role-scoped tools. A role whose collection lacks a tool the container's admin set had can no longer call it; that is the role table working as written.
- Steps get the skill prompt, behavioral rules and harness block the flow resolved, so step prompts grow by those blocks.
- Token-based termination counts real step usage, and VerifyingState's token-budget gate (over 100,000 tokens) can now report; a gate failure is recorded on the session and the flow still completes.

Tests: `tests/unit/fixes/test_w54_step_execution_context.py`.
