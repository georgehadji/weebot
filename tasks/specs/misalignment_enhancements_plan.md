# Misalignment Enhancements: Implementation Plan

**Source:** "How Coding Agents Fail Their Users: A Large-Scale Analysis of Developer-Agent
Misalignment in 20,574 Real-World Sessions" (Tang et al., 2026)

**Date:** 2026-06-13  
**Status:** Draft — ready for implementation

---

## Context and Scope

The paper identifies seven recurring misalignment symptoms (S1–S7) across 20,574 real
sessions. After reading the weebot codebase in full, three things are clear:

1. Several services that address root causes **already exist** but are **not wired in**:
   - `ConstraintExtractor` (extracts constraints for compaction preservation — but never
     used to block a violating step)
   - `IntentReviewService` (reviews IdeaContracts for the dreamer flow — but never invoked
     for direct user prompts entering `PlanActFlow`)

2. The verification layer (`VerifyingState`) checks summary consistency (CoVe) but not
   whether execution artifacts actually match what the user asked for — the S7 failure.

3. The UI fires execution immediately when the user submits a prompt. The user never sees
   the plan before steps run. The paper calls this the highest-leverage interface improvement.

**Enhancements in this plan:**

| # | Enhancement | Targets | Effort |
|---|-------------|---------|--------|
| 1 | Wire ConstraintExtractor into ExecutingState | S3 (38%) | Low |
| 2 | Connect IntentReviewService to PlanningState | S2 (27%) | Low |
| 3 | Artifact-based verification gates | S7 (23%) | Low |
| 4 | PlanReviewState + UI plan approval flow | S3, S4, interface | Medium |
| 5 | MisalignmentJournal → meta_notes | Cross-session (54% carry) | Medium |

**Build order:** 3 → 1 → 2 → 5 → 4 (least-invasive first, avoids blocking later work).

---

## Architectural Rules (must be respected throughout)

From `CLAUDE.md`:
- Dependency direction: `Interfaces → Infrastructure → Application → Domain`
- Domain must remain pure (no infrastructure imports)
- All new agent-facing events must be Pydantic `BaseEvent` subclasses
- New persistence must use the existing SQLite layer (WAL mode)
- States conform to the `FlowState` protocol: `async def execute(self, context, prompt)`
- No new environment variables without a constant in `weebot/config/constants.py`

---

## Enhancement 1 — Constraint Enforcement in ExecutingState

### Problem

`ConstraintExtractor` correctly identifies prohibitions (e.g., "DO NOT delete the user pool",
"never change the billing module"). `MemoryCompactor` re-injects them after compaction. But
**nothing checks whether a pending step violates them before execution begins**.

The paper's #1 symptom (S3, 38.33%) is constraint violation, and 73.68% of S3 cases are
caused by C6 — the agent *received* the constraint and ignored it. The fix is mechanical
enforcement, not a better LLM prompt.

### Files to change

| File | Change |
|------|--------|
| `weebot/application/services/constraint_extractor.py` | Add `check_step()` method |
| `weebot/application/flows/states/executing.py` | Add pre-step constraint check |

### 1.1 Add `check_step()` to `ConstraintExtractor`

```python
# weebot/application/services/constraint_extractor.py

import re

def check_step(self, step_description: str, constraints: List[Constraint]) -> List[Constraint]:
    """Return constraints that the step description appears to violate.

    Uses the same regex patterns as extract() but runs them against the step
    description rather than the full context. Negative constraints (priority 2)
    are matched: if the prohibited phrase appears in the step description,
    the constraint is flagged as violated.

    Only negative and safety constraints are checked — positive requirements
    are not checked here because partial progress is acceptable.
    """
    violations: List[Constraint] = []
    for c in constraints:
        if c.priority > 2:  # skip positive requirements
            continue
        # Extract the prohibited action from the constraint text.
        # Patterns like "do not X", "never X", "must not X" → extract X.
        action_match = re.search(
            r"(?:do\s+not|don't|never|must\s+not|shall\s+not|cannot|can't|avoid)\s+(.+)",
            c.text, re.IGNORECASE
        )
        if action_match:
            prohibited_phrase = action_match.group(1).strip().rstrip(".!;").lower()
            # Match key nouns/verbs from the prohibited phrase in the step description.
            # Use the first 5 tokens to avoid over-matching on long constraint sentences.
            key_tokens = prohibited_phrase.split()[:5]
            step_lower = step_description.lower()
            if sum(1 for tok in key_tokens if tok in step_lower) >= max(1, len(key_tokens) // 2):
                violations.append(c)
    return violations
```

**Why no LLM call:** The check is pure string matching. It has false negatives (misses
paraphrased violations) but zero false positives for exact constraint text. The paper's
examples of S3 all involved agents ignoring *clearly stated* constraints, not paraphrased
ones. An LLM check here would add latency to every step and still risk false negatives.

### 1.2 Add pre-step check in `ExecutingState.execute()`

In `weebot/application/flows/states/executing.py`, after line 67
(`step = context._plan.get_next_step()`), add:

```python
# ── Constraint enforcement (misalignment-fix Enhancement 1) ──────────
# Extract constraints from the original task prompt and check the
# next step before allowing execution to proceed.
_initial_prompt = (
    context._session.context.get("original_task", "")
    or context._session.context.get("last_prompt", "")
    or prompt
)
if _initial_prompt:
    from weebot.application.services.constraint_extractor import ConstraintExtractor
    _extractor = ConstraintExtractor()
    _constraints = _extractor.extract(_initial_prompt)
    _violations = _extractor.check_step(step.description, _constraints)
    if _violations:
        _violation_text = "; ".join(c.text for c in _violations[:2])
        logger.warning(
            "Step '%s' may violate constraint: %s — pausing for user",
            step.id, _violation_text,
        )
        yield WaitForUserEvent(
            question=(
                f"Step '{step.description}' may violate a stated constraint:\n"
                f"  {_violation_text}\n\n"
                f"Type 'proceed' to allow this step, or describe an alternative approach."
            )
        )
        return
# ──────────────────────────────────────────────────────────────────────
```

**Note:** `original_task` is already stored in session context by `PlanActFlow.run()` at line
394–401. `last_prompt` is set by the session router at creation. Both are safe fallbacks.

**Note on performance:** `ConstraintExtractor` is constructed per step call but is stateless.
If benchmarking reveals overhead, extract it to a `_constraint_extractor` instance on the
flow object. Do not optimise prematurely.

### 1.3 Tests

File: `tests/unit/test_constraint_enforcement.py`

```
TestConstraintExtractorCheckStep:
  - test_prohibit_delete_flagged: "DO NOT delete the user pool" → step "Delete user pool entries" → 1 violation
  - test_safety_constraint_flagged: "never expose API keys" → step "Print API key to logs" → 1 violation
  - test_unrelated_step_passes: "do not touch billing" → step "Update README" → 0 violations
  - test_positive_requirements_skipped: "always add tests" → step "Delete test file" → 0 violations (positive requirements not enforced here)
  - test_empty_constraints_passes: no constraints → step "Anything" → 0 violations

TestExecutingStateConstraintGate:
  - test_violating_step_emits_wait_for_user: mock flow with constraint in initial_prompt, step that matches → WaitForUserEvent emitted, state not advanced
  - test_non_violating_step_proceeds: step with no constraint match → normal execution continues
  - test_no_initial_prompt_skips_check: empty prompt → no constraint check, step proceeds
```

---

## Enhancement 2 — Intent Disambiguation Before Planning

### Problem

`IntentReviewService` already does LLM-based detection of underspecified prompts and returns
a `clarification_needed` list. But it's only wired into `IdeaGate` (the dreamer flow).
Direct user prompts entering `PlanActFlow` skip this entirely.

S2 (Misread Developer Intent, 26.95%): in 44.1% of cases the cause is C1 — an underspecified
instruction that the agent fills with a plausible but wrong interpretation. Asking 1–3
focused questions before planning costs 5 seconds and prevents a multi-minute misaligned run.

### Files to change

| File | Change |
|------|--------|
| `weebot/application/flows/states/planning.py` | Add intent gate before `CreatePlanCommand` |
| `weebot/domain/models/idea_contract.py` | Add `IdeaSource.USER_PROMPT` variant |

### 2.1 Add `USER_PROMPT` source to `IdeaSource`

```python
# weebot/domain/models/idea_contract.py — add to IdeaSource enum
USER_PROMPT = "user_prompt"
```

This keeps the existing `IdeaSource` enum clean and avoids forcing user prompts through
a conceptually wrong source type.

### 2.2 Add intent gate in `PlanningState.execute()`

In `weebot/application/flows/states/planning.py`, insert before the `CreatePlanCommand` block
(before line 70, `_plan_t0 = _time.monotonic()`):

```python
# ── Intent disambiguation gate (misalignment-fix Enhancement 2) ──────
# Skip if this is a continuation/resume (short prompts like "yes", "proceed").
# IntentReviewService.review() has a 5s timeout and fails open.
_is_continuation = len(prompt.split()) < 6 and prompt.strip().lower() in (
    "yes", "ok", "proceed", "continue", "approve", "go ahead", "y",
    "go", "do it", "run", "start",
)
if not _is_continuation and not context._session.context.get("_intent_reviewed"):
    try:
        from weebot.application.services.intent_review_service import IntentReviewService
        from weebot.domain.models.idea_contract import IdeaContract, IdeaSource
        from weebot.domain.models.intent_review import IntentVerdict

        _contract = IdeaContract(
            title=prompt[:80],
            prompt=prompt,
            source=IdeaSource.USER_PROMPT,
        )
        _review = await IntentReviewService(context._llm).review(_contract)

        if (
            _review.verdict == IntentVerdict.NOT_READY
            and _review.clarification_needed
        ):
            # Mark as reviewed so resume doesn't re-trigger this gate
            context._session = context._session.model_copy(update={
                "context": context._session.context.model_copy(
                    update={"_intent_reviewed": True}
                )
            })
            yield WaitForUserEvent(
                question="\n".join(
                    f"{i+1}. {q}" for i, q in enumerate(_review.clarification_needed[:3])
                )
            )
            return

        if _review.verdict == IntentVerdict.BLOCKED:
            yield EE(error=f"Request blocked by intent review: {_review.reasoning}")
            return

    except Exception as _exc:
        # Fail open — intent review failure must never block planning
        logger.debug("Intent review skipped: %s", _exc)

# Mark as reviewed regardless of outcome so we don't repeat on resume
context._session = context._session.model_copy(update={
    "context": context._session.context.model_copy(
        update={"_intent_reviewed": True}
    )
})
# ──────────────────────────────────────────────────────────────────────
```

**Design decisions:**
- `_intent_reviewed` flag in session context prevents the gate from re-firing on resume
  (when the user answers the clarification questions and `run()` is called again).
- Fail-open: any exception in `IntentReviewService` must never block planning.
- Continuations skip the gate entirely to avoid pestering the user on short follow-ups.
- Max 3 clarification questions (IntentReviewService already caps its output).

### 2.3 Tests

File: `tests/unit/test_intent_disambiguation.py`

```
TestIntentReviewInPlanningState:
  - test_ambiguous_prompt_emits_wait_for_user: mock IntentReviewService returning NOT_READY with 2 questions → WaitForUserEvent emitted with questions, planning blocked
  - test_blocked_prompt_emits_error: mock returning BLOCKED → ErrorEvent emitted
  - test_clear_prompt_proceeds: mock returning READY → CreatePlanCommand sent normally
  - test_intent_review_failure_proceeds: IntentReviewService raises exception → planning proceeds (fail-open)
  - test_continuation_skips_gate: prompt="yes" → no IntentReviewService call, planning proceeds
  - test_resume_skips_gate: session context has _intent_reviewed=True → no IntentReviewService call
```

---

## Enhancement 3 — Artifact-Based Completion Gates

### Problem

`VerifyingState` runs CoVe (Chain-of-Verification) on the *summary* — checking if the
summary is internally consistent. This is circular: the summary is generated by the agent,
and the consistency check uses the same LLM. The S7 failure mode (Inaccurate Self-Reporting,
22.58%) — e.g., agent claims "10/10 tasks complete" while a SQL column is missing — survives
CoVe because the summary is consistent with *itself*.

The fix is to read actual execution artifacts (ToolEvent outputs, file system state) rather
than asking the LLM to evaluate the summary.

### Files to change

| File | Change |
|------|--------|
| `weebot/application/flows/states/verifying.py` | Add `_gate_artifact_verification()` method, wire into `_gate_sweep()` |

### 3.1 Add `_gate_artifact_verification()` to `VerifyingState`

Add this method to `VerifyingState` in `weebot/application/flows/states/verifying.py`:

```python
async def _gate_artifact_verification(self, flow) -> list[str]:
    """Verify execution artifacts exist and tests passed.

    Reads ToolEvent results from the session — NOT the LLM summary.
    Returns a list of failed gate names.

    This gate addresses S7 (Inaccurate Self-Reporting): the agent
    claims completion but execution artifacts contradict it.
    """
    from pathlib import Path
    from weebot.domain.models.event import ToolEvent

    failures: list[str] = []
    session = flow._session

    # Gate A: File writes — every file written by file_editor must still exist.
    # The agent cannot claim it "created" a file that doesn't exist on disk.
    written_paths: list[str] = []
    for event in session.events:
        if not isinstance(event, ToolEvent):
            continue
        if event.tool_name not in ("file_editor", "edit_file", "write_file", "create_file"):
            continue
        # Extract file path from function args
        args = event.function_args or {}
        path = args.get("path") or args.get("file_path") or args.get("target_file", "")
        if path and event.status.value == "called":
            written_paths.append(str(path))

    missing: list[str] = []
    for p in written_paths:
        try:
            if not Path(p).exists():
                missing.append(p)
        except (OSError, ValueError):
            pass  # invalid path — skip, don't block

    if missing:
        _log.warning("Artifact gate: %d written files not found on disk: %s", len(missing), missing[:3])
        failures.append(f"written_files_missing:{','.join(missing[:2])}")

    # Gate B: Test runs — if a bash/shell step ran a test command and the last
    # visible output contains failure markers, flag it.
    # We check the ToolEvent.result directly — not the agent's summary of it.
    test_keywords = ("pytest", "npm test", "jest", "cargo test", "go test", "python -m pytest")
    for event in session.events:
        if not isinstance(event, ToolEvent):
            continue
        if event.tool_name not in ("bash", "shell_exec", "powershell"):
            continue
        cmd = str((event.function_args or {}).get("command", "")).lower()
        if not any(kw in cmd for kw in test_keywords):
            continue
        result = (event.result or "").lower()
        # Fail markers that are unambiguous
        if any(marker in result for marker in ("failed", "error", "assertion error", "test failed")):
            # Only flag if there is no "passed" line after the failure (partial runs)
            if "passed" not in result:
                _log.warning("Artifact gate: test failure detected in bash output")
                failures.append("test_run_failed")
                break

    return failures
```

### 3.2 Wire into `_gate_sweep()`

In `VerifyingState._gate_sweep()`, add the artifact check call at the end (before `if failures`):

```python
# Gate 6+7: Artifact verification (Enhancement 3)
artifact_failures = await self._gate_artifact_verification(flow)
failures.extend(artifact_failures)
```

### 3.3 Tests

File: `tests/unit/test_artifact_gates.py`

```
TestArtifactVerificationGate:
  - test_existing_file_passes: session with file_editor ToolEvent writing /tmp/test.py, file exists → no failures
  - test_missing_file_flagged: session with file_editor ToolEvent writing /nonexistent/path.py → failures contains "written_files_missing:..."
  - test_failed_pytest_output_flagged: session with bash ToolEvent running "pytest tests/" with result containing "2 failed" → failures contains "test_run_failed"
  - test_passing_tests_not_flagged: pytest result containing "5 passed" → no failures
  - test_no_tool_events_passes: empty session → no failures
  - test_invalid_path_does_not_raise: file_editor event with malformed path → no exception, no failures
  - test_gate_sweep_includes_artifact_results: full _gate_sweep call → artifact failures appear in returned list
```

---

## Enhancement 4 — Plan Review State and UI Approval Flow

### Problem

`new/page.tsx` does: `create_session → run() → navigate`. The user never sees the plan.
The paper's Section 5: *"interfaces supporting [developer calibration of] instruction
specificity, scope delegation, and trust in agent claims may matter as much as agent-side
improvements."* Plan review before execution directly targets both S3 (constraint violation)
and S4 (self-initiated overreach).

### Overview

The approach uses the existing `WaitForUserEvent`/resume mechanism to pause the flow:

```
PlanningState
     ↓ (plan created)
CritiquingState (existing)
     ↓ (critique passed)
PlanReviewState (NEW) ← emits PlanReviewEvent + WaitForUserEvent
     ↓ (user types "approve")         ↓ (user types modification)
ExecutingState                   PlanningState (re-plan with feedback)
```

On resume, `PlanActFlow.run()` detects the `plan_pending_approval` flag in session context
and routes back to plan review handling — it does **not** set a new `PlanReviewState`
instance (stateless approach avoids state serialisation complexity).

### Files to change

| File | Change |
|------|--------|
| `weebot/domain/models/event.py` | Add `PlanReviewEvent` |
| `weebot/application/flows/states/plan_review.py` | New file |
| `weebot/application/flows/states/critiquing.py` | Transition to PlanReviewState instead of ExecutingState |
| `weebot/application/flows/states/planning.py` | Transition to PlanReviewState after CritiquingState (or directly if no critic) |
| `weebot/application/flows/plan_act_flow.py` | Handle `plan_pending_approval` on resume |
| `weebot-ui/src/types/events.ts` | Add `PlanReviewEvent` type |
| `weebot-ui/src/app/sessions/[id]/page.tsx` | Render PlanReviewEvent as structured plan card |
| `weebot-ui/src/components/PlanReviewCard.tsx` | New component |

### 4.1 Add `PlanReviewEvent` to domain events

In `weebot/domain/models/event.py`, add after `WaitForUserEvent`:

```python
class PlanReviewEvent(BaseEvent):
    """Emitted when the flow pauses for the user to review a proposed plan.

    The UI renders this as a structured step list with an approve/modify input.
    plan_data mirrors PlanEvent.plan — a dict representation of the Plan model.
    """
    type: Literal["plan_review"] = "plan_review"
    plan_data: dict = Field(default_factory=dict)
    step_count: int = Field(default=0)
```

Also add `PlanReviewEvent` to the `AgentEvent` union at the bottom of the file:

```python
AgentEvent = Union[
    ErrorEvent, PlanEvent, StepEvent, ToolEvent, MessageEvent,
    TitleEvent, DoneEvent, WaitForUserEvent, NotificationEvent,
    ThoughtEvent, SteeringEvent, CanonicalizationEvent, TodoEvent,
    VerificationEvent, TrajectoryDiagnosisEvent, SessionStalenessEvent,
    MemoryPressureEvent, ScheduledJobEvent, LLMHealthEvent,
    PlanReviewEvent,  # ← add here
]
```

### 4.2 Create `PlanReviewState`

New file: `weebot/application/flows/states/plan_review.py`

```python
"""PlanReviewState — pauses flow for user to inspect and approve the plan.

Emits a PlanReviewEvent (renders as a structured plan card in the UI)
followed by a WaitForUserEvent. The user types "approve" / "yes" to proceed
or describes changes; the response is handled by PlanActFlow.run() on resume.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow

from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent, ErrorEvent, PlanReviewEvent, WaitForUserEvent

_log = logging.getLogger(__name__)

_APPROVE_TOKENS = frozenset({
    "approve", "approved", "yes", "ok", "proceed", "continue",
    "go", "go ahead", "run", "start", "lgtm", "y",
})


class PlanReviewState(FlowState):
    """Pauses execution for the user to review the proposed plan.

    Control flow:
      1. First call: emit PlanReviewEvent + WaitForUserEvent, set
         session context flag "plan_pending_approval", return.
      2. On resume: PlanActFlow.run() reads the flag and the user's
         response, then transitions to ExecutingState (approve) or
         PlanningState (modify). This state is not re-entered.
    """

    status = AgentStatus.PLANNING  # reuses PLANNING to avoid new enum value

    async def execute(
        self, context: "PlanActFlow", prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        if context._plan is None:
            yield ErrorEvent(error="PlanReviewState entered with no plan")
            from weebot.application.flows.states.executing import ExecutingState
            context.set_state(ExecutingState())
            return

        plan = context._plan
        _log.info(
            "Plan review: presenting %d-step plan '%s' to user",
            len(plan.steps), plan.title,
        )

        # Emit structured plan data for the UI to render
        yield PlanReviewEvent(
            plan_data=plan.model_dump(mode="json"),
            step_count=len(plan.steps),
        )

        # Mark plan as pending approval in session context
        context._session = context._session.model_copy(update={
            "context": context._session.context.model_copy(
                update={"plan_pending_approval": True}
            )
        })

        yield WaitForUserEvent(
            question=(
                f"Plan ready ({len(plan.steps)} step{'s' if len(plan.steps) != 1 else ''}):\n"
                + "\n".join(f"  {i+1}. {s.description}" for i, s in enumerate(plan.steps[:8]))
                + ("\n  ..." if len(plan.steps) > 8 else "")
                + "\n\nType 'approve' to start execution, or describe changes / constraints to add."
            )
        )
```

### 4.3 Handle `plan_pending_approval` in `PlanActFlow.run()`

In `weebot/application/flows/plan_act_flow.py`, in the `run()` method, add a branch in the
initial state-routing block (around line 410, after the `elif self._session.status ==
SessionStatus.WAITING` block):

```python
# ── Plan review resume (Enhancement 4) ──────────────────────────────
# When the session was paused for plan approval and the user has responded,
# handle the response here rather than routing to a re-entered state.
elif context._session.context.get("plan_pending_approval"):
    # Clear the flag
    self._session = self._session.model_copy(update={
        "context": self._session.context.model_copy(
            update={"plan_pending_approval": False}
        )
    })
    _response = prompt.strip().lower()
    if _response in _APPROVE_TOKENS or not _response:
        # User approved — proceed to execution
        self._log.info("Plan approved by user — proceeding to execution")
        self.set_state(ExecutingState())
    else:
        # User wants modifications — re-plan with their feedback as context
        self._log.info("User requested plan modification: %r", prompt[:80])
        # Inject the modification request as context for the next planning pass
        self._session = self._session.model_copy(update={
            "context": self._session.context.model_copy(
                update={
                    "_plan_modification_request": prompt,
                    "_intent_reviewed": False,  # allow re-review
                }
            )
        })
        self._plan = None
        self.set_state(PlanningState())
# ────────────────────────────────────────────────────────────────────
```

Import `_APPROVE_TOKENS` from `plan_review.py` at the top of `plan_act_flow.py` to avoid
duplication:
```python
from weebot.application.flows.states.plan_review import PlanReviewState, _APPROVE_TOKENS
```

Also inject the modification request into `PlannerAgent` when re-planning. In `PlanningState`,
read `_plan_modification_request` from session context and prepend it to the prompt:

```python
# In PlanningState.execute(), before CreatePlanCommand:
_mod_request = context._session.context.get("_plan_modification_request", "")
if _mod_request:
    prompt = f"{prompt}\n\n[User requested modification to prior plan: {_mod_request}]"
    # Clear so it doesn't persist to future re-plans
    context._session = context._session.model_copy(update={
        "context": context._session.context.model_copy(
            update={"_plan_modification_request": ""}
        )
    })
```

### 4.4 Wire PlanReviewState into CritiquingState and PlanningState

In `weebot/application/flows/states/critiquing.py`, replace the transition to `ExecutingState`
with `PlanReviewState`:

```python
# Before (current code):
context.set_state(ExecutingState())

# After:
from weebot.application.flows.states.plan_review import PlanReviewState
context.set_state(PlanReviewState())
```

(There are two transition points in CritiquingState — replace both.)

In `weebot/application/flows/states/planning.py`, where no critic is present:

```python
# Before (current code at end of execute()):
context.set_state(ExecutingState())

# After:
from weebot.application.flows.states.plan_review import PlanReviewState
context.set_state(PlanReviewState())
```

**Feature flag:** Add `WEEBOT_PLAN_REVIEW_ENABLED` environment variable (default `true`)
so existing automated tests and CLI usage can bypass plan review.

```python
# In PlanningState.execute() and CritiquingState.execute(), wrap the transition:
import os
if os.getenv("WEEBOT_PLAN_REVIEW_ENABLED", "true").lower() in ("true", "1", "yes"):
    from weebot.application.flows.states.plan_review import PlanReviewState
    context.set_state(PlanReviewState())
else:
    context.set_state(ExecutingState())
```

Add `WEEBOT_PLAN_REVIEW_ENABLED = True` to `weebot/config/constants.py`.

### 4.5 Frontend: Add `PlanReviewEvent` type

In `weebot-ui/src/types/events.ts`:

```typescript
export interface PlanStep {
  id: string;
  description: string;
  status: StepStatus;
}

export interface PlanReviewEvent extends BaseEvent {
  type: 'plan_review';
  plan_data: {
    title: string;
    steps: PlanStep[];
  };
  step_count: number;
}

// Add to AgentEvent union:
export type AgentEvent =
  | ErrorEvent
  | PlanEvent
  | StepEvent
  | ToolEvent
  | MessageEvent
  | TitleEvent
  | DoneEvent
  | WaitForUserEvent
  | NotificationEvent
  | PlanReviewEvent;  // ← add
```

### 4.6 Create `PlanReviewCard` component

New file: `weebot-ui/src/components/PlanReviewCard.tsx`

```tsx
"use client";

import { CheckCircle2, Circle, Edit3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PlanReviewEvent } from "@/types/events";

interface PlanReviewCardProps {
  event: PlanReviewEvent;
}

export function PlanReviewCard({ event }: PlanReviewCardProps) {
  const steps = event.plan_data?.steps ?? [];

  return (
    <Card className="border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Edit3 className="h-4 w-4 text-blue-600" />
          <CardTitle className="text-sm font-medium text-blue-800 dark:text-blue-200">
            Plan ready for review — {event.step_count} step{event.step_count !== 1 ? "s" : ""}
          </CardTitle>
        </div>
        {event.plan_data?.title && (
          <p className="text-xs text-muted-foreground">{event.plan_data.title}</p>
        )}
      </CardHeader>
      <CardContent>
        <ol className="space-y-1">
          {steps.map((step, i) => (
            <li key={step.id} className="flex items-start gap-2 text-sm">
              <span className="text-muted-foreground mt-0.5 shrink-0 w-5 text-right">
                {i + 1}.
              </span>
              <Circle className="h-3 w-3 mt-1 shrink-0 text-blue-400" />
              <span>{step.description}</span>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-muted-foreground italic">
          Type <Badge variant="outline" className="text-xs px-1 py-0">approve</Badge> below
          to start execution, or describe any changes needed.
        </p>
      </CardContent>
    </Card>
  );
}
```

### 4.7 Update session page to render PlanReviewCard

In `weebot-ui/src/app/sessions/[id]/page.tsx`, add `PlanReviewCard` to `EventCard`:

```tsx
import { PlanReviewCard } from "@/components/PlanReviewCard";
import { PlanReviewEvent } from "@/types/events";

// In EventCard switch:
case "plan_review":
  return <PlanReviewCard event={event as PlanReviewEvent} />;
```

Also update the `WaitForUserEvent` case to render more prominently when the prior event
was a `plan_review` (the input box should be visible and focused):

```tsx
case "wait_for_user":
  const wfu = event as WaitForUserEvent;
  return (
    <div className="rounded-lg border border-yellow-200 bg-yellow-50 dark:border-yellow-800 dark:bg-yellow-950 p-3">
      <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200 whitespace-pre-wrap">
        {wfu.question}
      </p>
    </div>
  );
```

### 4.8 Tests

File: `tests/unit/test_plan_review_state.py`

```
TestPlanReviewState:
  - test_emits_plan_review_event_and_wait: flow with plan → PlanReviewEvent + WaitForUserEvent emitted, plan_pending_approval set in context
  - test_no_plan_emits_error_and_advances: flow with no plan → ErrorEvent emitted, transitions to ExecutingState
  - test_plan_review_disabled_skips: WEEBOT_PLAN_REVIEW_ENABLED=false → PlanningState/CritiquingState go to ExecutingState directly

TestPlanActFlowPlanApproval:
  - test_approve_transitions_to_executing: resume with "approve" + plan_pending_approval=True → ExecutingState set, flag cleared
  - test_approve_case_insensitive: "APPROVE", "Yes", "ok" all transition to ExecutingState
  - test_modification_request_triggers_replanning: resume with "don't touch the database" → PlanningState set, modification stored in context
  - test_modification_injected_into_next_plan: _plan_modification_request in context → injected into planning prompt, then cleared
```

---

## Enhancement 5 — Misalignment Journal → meta_notes

### Problem

The paper found a 54.46% higher misalignment probability in the next session on the same
repository when the current session contained any misalignment. Weebot's `episodic_memory`
stores successful examples; there is no failure/avoidance signal. `PlannerAgent.create_plan()`
already accepts `meta_notes: list[str]` and injects them as avoidance hints — the injection
point exists, the data source does not.

### Design

- `MisalignmentEntry`: pure domain model (project path, constraint text, step description,
  correction message, timestamp)
- `MisalignmentJournalPort`: application port (read/write interface)
- `SQLiteMisalignmentJournal`: infrastructure implementation (new table in existing DB)
- Write entries when Enhancement 1 fires (constraint violation detected)
- Write entries when the user corrects the agent (user responds to `WaitForUserEvent` with
  substantive text rather than "approve")
- Feed recent entries into `PlannerAgent` via existing `meta_notes` parameter

### Files to change

| File | Change |
|------|--------|
| `weebot/domain/models/misalignment_entry.py` | New — `MisalignmentEntry` model |
| `weebot/application/ports/misalignment_journal_port.py` | New — port interface |
| `weebot/infrastructure/persistence/sqlite_misalignment_journal.py` | New — SQLite implementation |
| `weebot/application/flows/states/executing.py` | Write entry on constraint violation |
| `weebot/application/flows/plan_act_flow.py` | Feed journal entries as meta_notes at plan creation |
| `weebot/application/di/__init__.py` | Wire journal into DI container |

### 5.1 Domain model

New file: `weebot/domain/models/misalignment_entry.py`

```python
"""MisalignmentEntry — records a detected or user-corrected misalignment event."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class MisalignmentEntry(BaseModel):
    """An observed instance of agent-developer misalignment, for avoidance in future sessions."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(default="")
    project_path: str = Field(default="", description="Working directory, used to scope lookups")
    symptom: str = Field(
        default="",
        description="Short label: 'constraint_violation' | 'user_correction' | 'scope_overreach'"
    )
    constraint_text: Optional[str] = Field(default=None, description="The violated constraint, if known")
    step_description: Optional[str] = Field(default=None, description="The step that triggered the issue")
    correction_text: Optional[str] = Field(default=None, description="What the user said to correct it")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### 5.2 Application port

New file: `weebot/application/ports/misalignment_journal_port.py`

```python
"""Port: persistent misalignment journal for cross-session avoidance."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.misalignment_entry import MisalignmentEntry


class MisalignmentJournalPort(ABC):
    """Write and read misalignment entries scoped to a project path."""

    @abstractmethod
    async def record(self, entry: MisalignmentEntry) -> None:
        """Persist a new misalignment entry."""

    @abstractmethod
    async def get_recent(self, project_path: str, limit: int = 5) -> list[MisalignmentEntry]:
        """Return the most recent entries for a project, newest first."""
```

### 5.3 SQLite implementation

New file: `weebot/infrastructure/persistence/sqlite_misalignment_journal.py`

```python
"""SQLite-backed misalignment journal."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from weebot.application.ports.misalignment_journal_port import MisalignmentJournalPort
from weebot.domain.models.misalignment_entry import MisalignmentEntry

_log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS misalignment_journal (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    project_path TEXT NOT NULL,
    symptom     TEXT NOT NULL,
    constraint_text TEXT,
    step_description TEXT,
    correction_text TEXT,
    created_at  TEXT NOT NULL
)
"""

_INSERT = """
INSERT OR REPLACE INTO misalignment_journal
    (id, session_id, project_path, symptom, constraint_text, step_description, correction_text, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_RECENT = """
SELECT id, session_id, project_path, symptom, constraint_text,
       step_description, correction_text, created_at
FROM misalignment_journal
WHERE project_path = ?
ORDER BY created_at DESC
LIMIT ?
"""


class SQLiteMisalignmentJournal(MisalignmentJournalPort):
    """Stores misalignment entries in the weebot SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._ensure_table()

    def _ensure_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()

    async def record(self, entry: MisalignmentEntry) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(_INSERT, (
                    entry.id, entry.session_id, entry.project_path,
                    entry.symptom, entry.constraint_text, entry.step_description,
                    entry.correction_text, entry.created_at.isoformat(),
                ))
                conn.commit()
        except Exception as exc:
            _log.warning("MisalignmentJournal.record failed: %s", exc)

    async def get_recent(self, project_path: str, limit: int = 5) -> list[MisalignmentEntry]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(_SELECT_RECENT, (project_path, limit)).fetchall()
            return [
                MisalignmentEntry(
                    id=r[0], session_id=r[1], project_path=r[2], symptom=r[3],
                    constraint_text=r[4], step_description=r[5],
                    correction_text=r[6],
                    created_at=r[7],
                )
                for r in rows
            ]
        except Exception as exc:
            _log.warning("MisalignmentJournal.get_recent failed: %s", exc)
            return []
```

**SQLite concurrency:** Uses WAL mode (already configured in `sqlite_state_repo.py`). The
journal table is append-only with `INSERT OR REPLACE`, so write contention is minimal.

### 5.4 Write journal entries on constraint violation

In `ExecutingState.execute()`, after the `WaitForUserEvent` yield (Enhancement 1), add:

```python
# Record constraint violation in misalignment journal
_journal = getattr(context, "_misalignment_journal", None)
if _journal is not None:
    import asyncio
    from weebot.domain.models.misalignment_entry import MisalignmentEntry
    asyncio.ensure_future(_journal.record(MisalignmentEntry(
        session_id=context._session.id,
        project_path=context._session.context.get("working_dir", ""),
        symptom="constraint_violation",
        constraint_text=_violations[0].text if _violations else "",
        step_description=step.description,
    )))
```

**Why `ensure_future`:** Journal writes are best-effort and must not add latency to the
constraint check. Failures are swallowed in `SQLiteMisalignmentJournal.record()`.

Write entries on user correction (when user responds to `WaitForUserEvent` with substantive
text that is not an approval). Add to `PlanActFlow.run()` in the resume path:

```python
# In run(), when plan_pending_approval is True and user gave non-approval response:
if self._misalignment_journal is not None:
    from weebot.domain.models.misalignment_entry import MisalignmentEntry
    asyncio.ensure_future(self._misalignment_journal.record(MisalignmentEntry(
        session_id=self._session.id,
        project_path=self._session.context.get("working_dir", ""),
        symptom="user_correction",
        correction_text=prompt[:500],
    )))
```

### 5.5 Feed journal entries as meta_notes at plan creation

In `PlanActFlow.__init__()`, accept and store the journal:

```python
self._misalignment_journal: Optional[MisalignmentJournalPort] = cfg.misalignment_journal
```

Add `misalignment_journal: Optional[MisalignmentJournalPort] = None` to `PlanActFlowConfig`.

In `PlanningState.execute()`, before `CreatePlanCommand`, fetch recent entries and inject
them as `meta_notes`:

```python
_avoidance_notes: list[str] = []
_journal = getattr(context, "_misalignment_journal", None)
if _journal is not None:
    _project_path = context._session.context.get("working_dir", "")
    try:
        _recent = await _journal.get_recent(_project_path, limit=3)
        for entry in _recent:
            if entry.symptom == "constraint_violation" and entry.constraint_text:
                _avoidance_notes.append(
                    f"Previously violated: '{entry.constraint_text}' "
                    f"(step: '{entry.step_description}'). Avoid this pattern."
                )
            elif entry.symptom == "user_correction" and entry.correction_text:
                _avoidance_notes.append(
                    f"User correction from prior session: '{entry.correction_text[:120]}'"
                )
    except Exception:
        pass  # journal read failures must never block planning

# Merge with any existing meta_notes from episodic memory
# (CreatePlanCommand does not yet accept meta_notes — add this field)
```

**Note:** `CreatePlanCommand` does not currently have a `meta_notes` field. Add it:
```python
# weebot/application/cqrs/commands.py — CreatePlanCommand:
meta_notes: list[str] = Field(default_factory=list)
```

And pass it through to `PlannerAgent.create_plan(meta_notes=cmd.meta_notes)` in the
command handler.

### 5.6 Wire journal into DI container

In `weebot/application/di/__init__.py`, register `SQLiteMisalignmentJournal`:

```python
from weebot.infrastructure.persistence.sqlite_misalignment_journal import SQLiteMisalignmentJournal
from weebot.application.ports.misalignment_journal_port import MisalignmentJournalPort

container.register(
    MisalignmentJournalPort,
    SQLiteMisalignmentJournal(db_path=settings.db_path),
    singleton=True,
)
```

Inject into `PlanActFlowConfig` via `build_agent_runner()`.

### 5.7 Tests

File: `tests/unit/test_misalignment_journal.py`

```
TestMisalignmentEntry:
  - test_model_fields: valid construction, default id/timestamp generated

TestSQLiteMisalignmentJournal:
  - test_record_and_retrieve: write entry, get_recent returns it
  - test_project_path_scoping: entries from path A not returned for path B
  - test_limit_respected: 10 entries for project, limit=3 → 3 returned, newest first
  - test_record_failure_does_not_raise: corrupt db path → record() swallows exception
  - test_get_recent_failure_returns_empty: unreadable db → returns []

TestMisalignmentJournalIntegration:
  - test_constraint_violation_writes_entry: ExecutingState detects violation → journal.record() called with symptom="constraint_violation"
  - test_user_correction_writes_entry: user sends non-approve response to plan review → journal.record() called with symptom="user_correction"
  - test_journal_entries_become_meta_notes: 2 recent entries → PlanningState injects them as avoidance hints in CreatePlanCommand
  - test_empty_journal_does_not_block_planning: no entries → planning proceeds normally
```

---

## Build Order

Implement in this order to avoid merge conflicts and enable incremental validation:

```
Step 1: Enhancement 3 (artifact gates)
  → Only modifies VerifyingState; isolated; no new files; tests pass immediately.

Step 2: Enhancement 1 (constraint enforcement)
  → Adds check_step() to ConstraintExtractor; modifies ExecutingState.
  → Tests for step 1 remain green.

Step 3: Enhancement 2 (intent disambiguation)
  → Modifies PlanningState; adds IdeaSource.USER_PROMPT; no infrastructure changes.
  → WEEBOT_PLAN_REVIEW_ENABLED not yet wired, so existing tests unaffected.

Step 4: Enhancement 5 (misalignment journal)
  → Adds domain model, port, SQLite impl; modifies ExecutingState and PlanActFlow.
  → New table in existing DB; no existing table changes.

Step 5: Enhancement 4 (plan review)
  → Most invasive: new event type, new state, changes to two existing states,
    PlanActFlow run() routing, and frontend changes.
  → Feature-flagged; existing integration tests set WEEBOT_PLAN_REVIEW_ENABLED=false.
```

---

## Testing Strategy

### Unit tests (one file per enhancement, as specified above)

All new tests follow the AAA (Arrange-Act-Assert) pattern using `pytest` + `pytest-asyncio`.
Mocking policy: mock the LLM (`LLMPort`) and journal (`MisalignmentJournalPort`) at the
port boundary; never mock internal service internals.

### Architecture fitness tests

The existing `tests/unit/test_architecture_fitness.py` uses import-linter to enforce the
dependency rule. Verify new files comply:

- `weebot/domain/models/misalignment_entry.py` — no non-domain imports ✓
- `weebot/application/ports/misalignment_journal_port.py` — only domain imports ✓
- `weebot/infrastructure/persistence/sqlite_misalignment_journal.py` — imports port + domain ✓
- `weebot/application/flows/states/plan_review.py` — imports domain + ports ✓

### Integration tests

Add to `tests/integration/` (or extend existing):
- Full `PlanActFlow` run with constraint in prompt → WaitForUserEvent emitted, journal entry written
- Full `PlanActFlow` run with ambiguous prompt → clarification questions emitted
- Plan review → approve → execution proceeds
- Plan review → modify → re-plan with modification context

### Regression gate

Before merging: `pytest tests/ -x` must pass. Enhancement 4 transitions must be
feature-flagged off (`WEEBOT_PLAN_REVIEW_ENABLED=false`) for all existing tests that don't
explicitly test plan review.

---

## Architecture Compliance Checklist

- [ ] No domain model imports application or infrastructure code
- [ ] All new events are Pydantic `BaseEvent` subclasses with a unique `type` literal
- [ ] New events are added to the `AgentEvent` union in `event.py`
- [ ] New events mirror in `weebot-ui/src/types/events.ts`
- [ ] New SQLite tables use `CREATE TABLE IF NOT EXISTS` (idempotent)
- [ ] New environment variables have constants in `weebot/config/constants.py`
- [ ] All new services registered in `weebot/application/di/__init__.py`
- [ ] All error paths fail open (never block the core flow)
- [ ] No new mandatory dependencies added to `requirements.txt`
- [ ] Import-linter passes after each enhancement

---

## Done Criteria

Each enhancement is done when:

1. Unit tests pass (`pytest tests/unit/test_<enhancement>.py -v`)
2. Architecture fitness tests pass (`pytest tests/unit/test_architecture_fitness.py -v`)
3. No regressions in the full test suite (`pytest tests/ -x`)
4. The specific misalignment symptom it targets is reproducibly prevented in a manual test:
   - E1: prompt "never delete X" → step "Delete X" → WaitForUserEvent fires
   - E2: ambiguous prompt → clarification questions before plan appears
   - E3: file_editor step + file deleted before VerifyingState → gate failure recorded
   - E4: plan created → user sees steps → types "approve" → execution begins
   - E5: prior session's constraint violation → next session's plan avoids it

---

## Open Questions / Risks

1. **Plan review user friction:** Requiring approval for every plan will slow simple tasks.
   Consider auto-approving single-step plans or SIMPLE-scope tasks (the `ScopeClassifier`
   already classifies these). Add `WEEBOT_PLAN_REVIEW_MIN_STEPS` constant (default: 2) —
   plans with fewer steps skip review.

2. **Intent disambiguation false positives:** `IntentReviewService` uses an LLM and may
   flag clear prompts as needing clarification. The 5-second timeout and `_intent_reviewed`
   flag bound the damage, but monitor rate of false fires in production logs.

3. **Constraint matching precision:** The regex-based `check_step()` has false negatives for
   paraphrased violations. This is acceptable — it catches the paper's representative cases
   (exact text like "DO NOT change the user pool") without adding LLM latency to every step.
   A future enhancement could use embedding similarity for fuzzy matching.

4. **MisalignmentJournal and project_path:** `working_dir` may not be consistently set in
   session context. Audit all session creation paths to ensure it's populated, or fall back
   to repository URL / session agent_id as the scoping key.
