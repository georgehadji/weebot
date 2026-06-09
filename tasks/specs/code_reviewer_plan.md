# Code Reviewer Agent — Implementation Plan

**Feature:** `ReviewingState` — per-step LLM code review between `ExecutingState` and the next step.  
**Approach:** Approach 1 from the architecture research: a first-class `FlowState` that mirrors the existing `CritiquingState` / `VerifyingState` pattern exactly.  
**Status:** Draft — ready to implement  
**Effort:** ~250 lines of new code across 3 new files, ~30 lines of edits across 4 existing files

---

## 1. Architectural Context

### Where it fits in the state machine

```
PlanningState
  → CritiquingState     (plan-level LLM validation before any execution)
    → PremortmState     (prospective risk injection into plan.message)
      → ExecutingState  (per-step: quality check → mark COMPLETED → hooks → KG)
          → ReviewingState  ← NEW: per-step code review after step completes
              approved  → ExecutingState (next step)
              revise    → ExecutingState (same step, retry_count+1, hint injected)
              reject    → UpdatingState (trigger replanning)
          → VerifyingState  (CoVe fact-check when all steps done)
            → SummarizingState → CompletedState
```

### Design principles observed in this codebase

1. **Port → Service pattern**: every LLM-backed capability has an abstract `Port` (ABC) in
   `application/ports/` and a concrete `Service` in `application/services/`. The port is what
   the flow wires; the service is the real implementation.
   - Template: `PlanCriticPort` / `PlanCriticService`

2. **FlowState pattern**: states are `FlowState` subclasses. They receive the full `PlanActFlow`
   context but are constructed with the services they need at `set_state()` call time.
   - Template: `CritiquingState(critic=...)`

3. **Fail-open by default**: every LLM call wraps its error path with a graceful approved-default
   so a timeout never blocks the flow. Same budget as `StepResultValidator` (fast, single call).

4. **Opt-in via config**: new capabilities appear as `Optional[Any] = None` in
   `PlanActFlowConfig`. `None` means skip silently — backward-compatible.

5. **Immutable plan mutations**: step updates always go through `plan.replace_step()` or
   `plan.update_step_status()` which return new `Plan` instances. Never mutate in place.

6. **Observable via ThoughtEvent**: every LLM decision yields a `ThoughtEvent` so the
   CLI/WebSocket/logs surface it without any extra wiring.

---

## 2. Files to Create (new)

| # | File | Purpose |
|---|------|---------|
| 1 | `weebot/domain/models/code_review.py` | `CodeReviewResult` domain model |
| 2 | `weebot/application/ports/code_reviewer_port.py` | Abstract port (ABC) |
| 3 | `weebot/application/services/code_reviewer_service.py` | LLM-backed implementation |
| 4 | `weebot/application/flows/states/reviewing.py` | `ReviewingState` FlowState |
| 5 | `tests/unit/test_code_reviewer_service.py` | Unit tests for service |
| 6 | `tests/unit/test_reviewing_state.py` | Unit tests for state |

---

## 3. Files to Edit (existing)

| File | Change | Lines affected |
|------|--------|---------------|
| `weebot/application/flows/states/base.py` | Add `REVIEWING = "reviewing"` to `AgentStatus` | +1 line |
| `weebot/application/models/plan_act_flow_config.py` | Add `code_reviewer: Optional[Any] = None` field | +4 lines |
| `weebot/application/flows/plan_act_flow.py` | Store `_code_reviewer` from config | +3 lines |
| `weebot/application/flows/states/executing.py` | Replace final `set_state(ExecutingState())` with conditional | +8 lines, -1 line |

---

## 4. Phase-by-Phase Implementation

### Phase 1 — Domain Model

**File:** `weebot/domain/models/code_review.py` *(new)*

The domain layer must stay pure — no imports from application or infrastructure.
This model lives beside `PlanCritique` conceptually, but gets its own file because
it's step-scoped (not plan-scoped) and has different semantics.

```python
"""CodeReviewResult — immutable result of a per-step code review."""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class CodeReviewResult(BaseModel):
    """Result of an LLM code review on a single executed step.

    Mirrors PlanCritique in shape but is scoped to one step's output
    rather than an entire plan.
    """
    step_id: str = Field(default="", description="The step that was reviewed")
    verdict: Literal["approved", "revise", "reject"] = Field(
        default="approved",
        description=(
            "approved — no issues, proceed to next step; "
            "revise   — issues found, retry this step with hint injected; "
            "reject   — unrecoverable, trigger replanning"
        ),
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Specific findings: security holes, bugs, missing error handling, etc.",
    )
    hint: str = Field(
        default="",
        description="Actionable improvement instruction injected into step description on revise",
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Reviewer confidence in the verdict (lower = more uncertain)",
    )
    severity: Literal["info", "warning", "error"] = Field(
        default="info",
        description="info → cosmetic; warning → quality; error → correctness/security",
    )

    @property
    def is_actionable(self) -> bool:
        """True when the verdict requires the flow to change its path."""
        return self.verdict in ("revise", "reject")

    @property
    def summary(self) -> str:
        """One-line summary for logging and ThoughtEvent body."""
        if not self.issues:
            return f"[{self.verdict.upper()}] No issues found."
        issues_str = "; ".join(self.issues[:3])
        more = f" (+{len(self.issues) - 3} more)" if len(self.issues) > 3 else ""
        return f"[{self.verdict.upper()}] {issues_str}{more}"
```

**Why a separate file instead of appending to `plan.py`?**
`plan.py` already contains `Plan`, `Step`, `PlanCritique`. Adding `CodeReviewResult`
would grow it past 800 lines and violate the single-responsibility rule. Separate file
keeps each model cohesive and makes imports explicit.

---

### Phase 2 — Port Definition

**File:** `weebot/application/ports/code_reviewer_port.py` *(new)*

```python
"""CodeReviewerPort — abstract interface for per-step code review."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.plan import Step


class CodeReviewerPort(ABC):
    """Interface for LLM-backed per-step code review.

    Called by ReviewingState after ExecutingState marks a step COMPLETED
    and before the flow advances to the next step.

    Implementations must be fail-open: a timeout or parse error must return
    a default CodeReviewResult(verdict="approved") rather than propagating
    the exception into the flow.
    """

    @abstractmethod
    async def review(self, step: Step, context: dict[str, Any]) -> CodeReviewResult:
        """Review the output of a completed step.

        Args:
            step: The just-completed step. Fields of interest:
                  - step.description: what the executor was asked to do
                  - step.result:      what the executor reported doing
                  - step.id:          for the CodeReviewResult.step_id
            context: Execution context dict. Keys provided by ReviewingState:
                  - "task":         original user task prompt
                  - "step_events":  list of serialised AgentEvent dicts from
                                    this step's execution (tool calls, output)
                  - "completed_steps": int, how many steps have run so far
                  - "plan_title":   str, the plan title for context

        Returns:
            CodeReviewResult with verdict, issues, hint, and confidence.
            Must never raise — return approved default on any failure.
        """
        ...
```

**Why an ABC port?**
- Follows the dependency inversion principle: `ReviewingState` depends on the abstract
  `CodeReviewerPort`, not on `CodeReviewerService` directly.
- Allows test doubles: `AsyncMock(spec=CodeReviewerPort)` for unit tests.
- Future implementations (e.g., a static-analysis-backed reviewer) can plug in without
  touching the state machine.

---

### Phase 3 — Service Implementation

**File:** `weebot/application/services/code_reviewer_service.py` *(new)*

```python
"""CodeReviewerService — LLM-backed per-step code review.

Uses MODEL_CODE_REVIEW (grok-4.3 — reasoning, 1M context) to review the
output of each code-producing step before the flow advances.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.code_reviewer_port import CodeReviewerPort
from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.plan import Step

logger = logging.getLogger(__name__)

_REVIEWER_SYSTEM_PROMPT = """You are a senior code reviewer. A coding agent just completed
one step of a multi-step task. Review what it did and flag real problems only.

Check for:
1. Security issues: hardcoded secrets, unvalidated input, SQL injection, path traversal
2. Correctness bugs: off-by-one errors, wrong logic, missing edge cases, incorrect API usage
3. Missing error handling: uncaught exceptions, unhandled failure modes
4. Architectural violations: wrong layer imports, mutating shared state, circular deps
5. Scope creep: the step did something outside its description

Do NOT flag:
- Style preferences, minor naming choices, or improvements unrelated to correctness
- Hypothetical future issues
- Things that are handled in other steps

Respond with a single JSON object (no markdown, no fences):
{
  "verdict":    "approved" | "revise" | "reject",
  "issues":     ["specific finding 1", ...],
  "hint":       "one actionable instruction for the agent if verdict is revise",
  "confidence": 0.0-1.0,
  "severity":   "info" | "warning" | "error"
}

Use "reject" only for unrecoverable issues (security breach, data loss risk).
Use "revise" for fixable correctness/error-handling problems.
Use "approved" when the step is good enough to proceed."""

# Prompt and temperature constants (mirror plan_critic.py naming)
_MAX_TOKENS = 512
_TEMPERATURE = 0.1   # low temperature for consistent structured output


class CodeReviewerService(CodeReviewerPort):
    """LLM-backed code reviewer. Fail-open: returns approved on any failure."""

    def __init__(
        self,
        llm: LLMPort,
        timeout_seconds: float = 8.0,
    ) -> None:
        """
        Args:
            llm: LLMPort instance. Should target MODEL_CODE_REVIEW (grok-4.3).
            timeout_seconds: Max wait for the LLM call. Returns approved on timeout.
        """
        self._llm = llm
        self._timeout_seconds = timeout_seconds

    async def review(self, step: Step, context: dict[str, Any]) -> CodeReviewResult:
        """Review a completed step's output. Never raises — returns approved on failure."""
        try:
            prompt = self._build_prompt(step, context)
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _REVIEWER_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
            )

            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]

            data = json.loads(raw)
            result = CodeReviewResult(
                step_id=step.id,
                verdict=data.get("verdict", "approved"),
                issues=data.get("issues", []),
                hint=data.get("hint", ""),
                confidence=float(data.get("confidence", 1.0)),
                severity=data.get("severity", "info"),
            )
            logger.info(
                "Code review step=%s verdict=%s confidence=%.2f issues=%d",
                step.id, result.verdict, result.confidence, len(result.issues),
            )
            return result

        except Exception as exc:
            logger.warning(
                "Code reviewer failed for step %s (%s). Proceeding as approved.",
                step.id, exc,
            )
            return CodeReviewResult(step_id=step.id, verdict="approved")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, step: Step, context: dict[str, Any]) -> str:
        task        = context.get("task", "unknown task")
        plan_title  = context.get("plan_title", "")
        n_complete  = context.get("completed_steps", 0)
        step_events = context.get("step_events", [])

        # Render last 10 tool events for context (truncated for token budget)
        tool_lines = self._render_tool_events(step_events, max_events=10)

        result_section = (
            f"Result reported: {step.result}"
            if step.result
            else "Result reported: (none)"
        )

        return (
            f"## Task\n{task}\n\n"
            f"## Plan\n{plan_title}  (step {n_complete + 1})\n\n"
            f"## Step Description\n{step.description}\n\n"
            f"## {result_section}\n\n"
            f"## Tool Calls Made\n{tool_lines or '(no tool call events recorded)'}"
        )

    @staticmethod
    def _render_tool_events(events: list[Any], max_events: int) -> str:
        """Extract tool-call summaries from raw serialised event dicts."""
        lines = []
        for e in events:
            if not isinstance(e, dict):
                continue
            if e.get("type") == "tool":
                tool_name  = e.get("tool_name", "?")
                tool_input = str(e.get("tool_input", ""))[:200]
                lines.append(f"- {tool_name}({tool_input})")
            if len(lines) >= max_events:
                break
        return "\n".join(lines)
```

**Key decisions:**
- `timeout_seconds=8.0` — generous because grok-4.3 is a reasoning model; `plan_critic`
  uses 5s for a simpler task.
- `_MAX_TOKENS=512` — reviews should be brief; we reject lengthy reasoning in favour of
  a structured verdict.
- `_TEMPERATURE=0.1` — deterministic structured output; same rationale as `plan_critic`.
- The `_render_tool_events` helper extracts only tool-call dicts from the raw CQRS event
  list, keeping the prompt compact. It does NOT import `AgentEvent` to avoid coupling.

---

### Phase 4 — AgentStatus Extension

**File:** `weebot/application/flows/states/base.py`

Add one value to the `AgentStatus` enum. This value drives `PlanActFlow.set_state()`
which updates `context._status` and emits a `StepEvent` for observability.

```python
class AgentStatus(str, Enum):
    IDLE        = "idle"
    PLANNING    = "planning"
    EXECUTING   = "executing"
    REVIEWING   = "reviewing"   # ← ADD THIS
    UPDATING    = "updating"
    VERIFYING   = "verifying"
    SUMMARIZING = "summarizing"
    COMPLETED   = "completed"
```

**Note:** `CritiquingState` currently reuses `PLANNING` to avoid adding a new enum value
(comment on line 31 of `critiquing.py`). We do NOT follow that workaround here — a
first-class `REVIEWING` value is correct and makes metrics/logging unambiguous.

---

### Phase 5 — ReviewingState

**File:** `weebot/application/flows/states/reviewing.py` *(new)*

```python
"""ReviewingState — per-step LLM code review between execution and the next step.

Inserted by ExecutingState after marking a step COMPLETED, when the step
is detected as having produced code. Verdicts:
  approved → ExecutingState (advance to next step)
  revise   → ExecutingState (same step, retry_count+1, hint injected)
  reject   → UpdatingState  (mark step FAILED, trigger replanning)
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow

from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.application.ports.code_reviewer_port import CodeReviewerPort
from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.event import AgentEvent, ThoughtEvent
from weebot.domain.models.plan import Step, StepStatus

logger = logging.getLogger(__name__)

# Retry cap: reviewer may request at most this many revisions per step.
# Prevents an infinite revise loop if the model keeps finding the same issue.
_MAX_REVIEW_RETRIES = 2


class ReviewingState(FlowState):
    """LLM code review gate between step completion and next-step dispatch."""

    status = AgentStatus.REVIEWING

    def __init__(
        self,
        step: Step,
        reviewer: CodeReviewerPort | None = None,
        step_events: list[Any] | None = None,
    ) -> None:
        """
        Args:
            step:        The just-completed step (status=COMPLETED at construction).
            reviewer:    CodeReviewerPort instance. If None, falls through immediately.
            step_events: Raw serialised AgentEvent dicts from this step's execution,
                         forwarded to the reviewer for tool-call context.
        """
        self._step = step
        self._reviewer = reviewer
        self._step_events: list[Any] = step_events or []

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.executing import ExecutingState
        from weebot.application.flows.states.updating import UpdatingState

        # ── Fast path: no reviewer configured ──────────────────────────
        if self._reviewer is None:
            logger.debug("No code reviewer configured — passing through")
            context.set_state(ExecutingState())
            return

        # ── Guard: don't review a step that has already been revised too many times ──
        if self._step.retry_count >= _MAX_REVIEW_RETRIES:
            logger.info(
                "Step %s has reached review retry cap (%d) — approving automatically",
                self._step.id, _MAX_REVIEW_RETRIES,
            )
            context.set_state(ExecutingState())
            return

        if context._plan is None:
            logger.warning("ReviewingState: no plan on context — skipping")
            context.set_state(ExecutingState())
            return

        # ── Build review context dict ────────────────────────────────
        completed_count = len(context._plan.get_completed_steps())
        review_context: dict[str, Any] = {
            "task":            prompt,
            "plan_title":      context._plan.title,
            "completed_steps": completed_count,
            "step_events":     self._step_events,
        }

        # ── Call the reviewer ────────────────────────────────────────
        logger.info(
            "Reviewing step %s: %s",
            self._step.id, self._step.description[:80],
        )
        result: CodeReviewResult = await self._reviewer.review(
            self._step, review_context
        )

        # ── Emit ThoughtEvent for CLI/WebSocket/logs ─────────────────
        yield ThoughtEvent(
            step_id=self._step.id,
            thought=self._format_thought(result),
        )

        # ── Route based on verdict ───────────────────────────────────
        if result.verdict == "approved":
            logger.info("Review APPROVED step %s", self._step.id)
            context.set_state(ExecutingState())

        elif result.verdict == "revise":
            logger.info(
                "Review REVISE step %s — hint: %s",
                self._step.id, result.hint[:120],
            )
            revised_step = self._step.model_copy(update={
                "status":      StepStatus.PENDING,
                "retry_count": self._step.retry_count + 1,
                "description": (
                    f"{self._step.description}\n"
                    f"[Code review hint: {result.hint}]"
                    if result.hint
                    else self._step.description
                ),
            })
            context._plan = context._plan.replace_step(self._step.id, revised_step)
            context.set_state(ExecutingState())

        else:  # "reject"
            logger.warning(
                "Review REJECTED step %s — %s",
                self._step.id, result.summary,
            )
            context._plan = context._plan.update_step_status(
                self._step.id,
                StepStatus.FAILED,
                result=f"[Code review rejected] {result.summary}",
            )
            context.set_state(UpdatingState())

    @staticmethod
    def _format_thought(result: CodeReviewResult) -> str:
        lines = [
            f"**Code Review** — Verdict: {result.verdict.upper()}, "
            f"Confidence: {result.confidence:.0%}, "
            f"Severity: {result.severity}",
        ]
        if result.issues:
            lines.append("\n**Issues:**")
            lines.extend(f"- {issue}" for issue in result.issues)
        if result.hint and result.verdict == "revise":
            lines.append(f"\n**Hint:** {result.hint}")
        return "\n".join(lines)
```

**Key decisions:**
- `_MAX_REVIEW_RETRIES = 2`: mirrors the `step.retry_count < 1` cap in
  `StepResultValidator`. Prevents a feedback loop where the reviewer keeps flagging the
  same issue on each re-execution.
- `step_events` passed at construction: the state is constructed at the moment the events
  are in scope (inside `ExecutingState.execute()`), so passing them at `__init__` is the
  cleanest ownership model. No shared mutable state on the flow context.
- `model_copy(update=...)` for step mutation: immutable as required by coding-style rules.
- No direct access to `self._reviewer` in the `UpdatingState` path — `UpdatingState`
  replans without a reviewer involved, keeping concerns separated.

---

### Phase 6 — Config Extension

**File:** `weebot/application/models/plan_act_flow_config.py`

Under the `# ── Critique & validation ───` section, add one field:

```python
# ── Critique & validation ───────────────────────────────────────────
truth_binder:   Optional[Any] = None  # TruthBinder
plan_critic:    Optional[Any] = None  # PlanCriticService
code_reviewer:  Optional[Any] = None  # CodeReviewerPort — per-step code review
```

Typed as `Optional[Any]` (not `Optional[CodeReviewerPort]`) for the same reason
`plan_critic` uses `Optional[Any]`: avoids importing the application service layer into
the models module, which would create a circular import path.

---

### Phase 7 — Flow Wiring

**File:** `weebot/application/flows/plan_act_flow.py`

Three changes, all mechanical mirrors of how `plan_critic` is wired.

**A. Accept `code_reviewer` in `__init__`** (in the legacy kwargs block, near `plan_critic`):

```python
code_reviewer: Optional[Any] = None,   # CodeReviewerPort — per-step code review
```

**B. Store on `self` from config** (in the `__init__` body where config attributes are
unpacked, near the `_plan_critic` assignment):

```python
self._code_reviewer = (
    config.code_reviewer
    if config is not None
    else code_reviewer
)
```

**C. No state transition changes in the flow itself** — the transition is handled inside
`ExecutingState` (Phase 8), which already has full access to `context._code_reviewer`.

---

### Phase 8 — Transition Insertion in ExecutingState

**File:** `weebot/application/flows/states/executing.py`

This is the only structural edit to existing execution logic. The insertion point is at
the very end of `execute()`, replacing the final `context.set_state(ExecutingState())`.

**Before (line 294):**
```python
context.set_state(ExecutingState())
```

**After:**
```python
if (
    getattr(context, "_code_reviewer", None) is not None
    and _is_code_step(step)
    and step.retry_count < _MAX_REVIEW_RETRIES_GATE
):
    from weebot.application.flows.states.reviewing import ReviewingState
    context.set_state(
        ReviewingState(
            step=step,
            reviewer=context._code_reviewer,
            step_events=list(_current_step_events),
        )
    )
else:
    context.set_state(ExecutingState())
```

**Supporting additions** — add these at module scope (after the imports, before the class):

```python
# Tool names whose presence indicates a code-producing step
_CODE_TOOL_NAMES: frozenset[str] = frozenset({
    "file_editor", "edit_file", "write_file", "create_file",
    "bash", "shell", "execute_command", "run_command",
    "write", "edit", "patch",
})

# Step description keywords that indicate code production
_CODE_KEYWORDS: frozenset[str] = frozenset({
    "implement", "write", "create file", "edit file", "modify",
    "add function", "add method", "add class", "fix bug",
    "refactor", "update file", "generate", "scaffold", "build",
    "code", "script", "patch",
})

# Reviewer retries gate — must match _MAX_REVIEW_RETRIES in ReviewingState
_MAX_REVIEW_RETRIES_GATE: int = 2


def _is_code_step(step: "Step") -> bool:
    """Return True if this step likely produced or modified code.

    Uses both tool-event inspection and keyword matching. Tool events are
    checked first (authoritative); keywords are the fallback when events
    are not available.
    """
    desc_lower = step.description.lower()
    return any(kw in desc_lower for kw in _CODE_KEYWORDS)
```

**`_current_step_events` capturing** — add one line in the event-consumption loop
(lines 154–165 of `executing.py`) to capture events for the reviewer:

```python
# Capture events for the code reviewer (added alongside existing event consumption)
_current_step_events: list[Any] = []
for event in reconstruct_events(cmd_result.data.get("events", [])):
    _current_step_events.append(event)   # ← ADD
    await context._emit(event)
    yield event
    ...
```

**Why capture events here and pass to `ReviewingState`?**
`cmd_result` goes out of scope when `execute()` returns. Storing events on the flow
context (`context._step_events`) would pollute the shared state. Passing them at
`ReviewingState.__init__` time respects each state's ownership of its own data.

**Why not use `step.result` alone?**
`step.result` is set by the executor's summary string, which is often too high-level to
review. Tool-call events reveal exactly what files were written, what shell commands ran,
and what the actual outputs were — much richer input for a code reviewer.

---

## 5. Test Plan

### Unit tests — `CodeReviewerService`

**File:** `tests/unit/test_code_reviewer_service.py`

| Test | What it verifies |
|------|-----------------|
| `test_approved_verdict_returned` | LLM returns valid JSON `approved` → `CodeReviewResult(verdict="approved")` |
| `test_revise_verdict_with_hint` | LLM returns `revise` with hint → hint is preserved |
| `test_reject_verdict_with_issues` | LLM returns `reject` with issues list → issues preserved |
| `test_timeout_returns_approved` | LLM raises `asyncio.TimeoutError` → `approved` default, no raise |
| `test_json_parse_failure_returns_approved` | LLM returns malformed JSON → `approved` default, no raise |
| `test_markdown_fence_stripped` | LLM wraps JSON in ` ```json ``` ` → stripped correctly |
| `test_confidence_clamped_to_range` | Confidence of 1.5 from LLM → clamped to 1.0 by Pydantic |
| `test_tool_events_rendered_in_prompt` | Step events appear in the prompt passed to LLM |
| `test_empty_step_result_handled` | `step.result = None` → no crash, valid prompt |

Pattern: `AsyncMock(spec=LLMPort)` returning a mock `LLMResponse` with `.content`.

### Unit tests — `ReviewingState`

**File:** `tests/unit/test_reviewing_state.py`

| Test | What it verifies |
|------|-----------------|
| `test_no_reviewer_falls_through` | `reviewer=None` → `ExecutingState` set, no LLM calls |
| `test_approved_advances_to_next_step` | `approved` verdict → `context.set_state(ExecutingState())` |
| `test_revise_injects_hint_and_retries` | `revise` verdict → step description has hint, `retry_count+1`, status=PENDING, `ExecutingState` |
| `test_revise_without_hint_no_bracket` | `revise` with empty hint → description unchanged |
| `test_reject_marks_step_failed` | `reject` verdict → step FAILED, `UpdatingState` |
| `test_retry_cap_prevents_loop` | `step.retry_count >= _MAX_REVIEW_RETRIES` → automatic approved |
| `test_thought_event_yielded` | `ThoughtEvent` is always yielded with verdict in body |
| `test_no_plan_falls_through` | `context._plan = None` → graceful fallthrough |

Pattern: mock `context` (MagicMock with `_plan`, `_code_reviewer`, `set_state`),
mock `reviewer` (AsyncMock returning `CodeReviewResult`).

---

## 6. Integration Notes (no implementation required)

### DI Container
`CodeReviewerService` requires only a `LLMPort`. The container already provides this.
The reviewer is wired at call-site (same pattern as `PlanCriticService`):

```python
# In whatever builds PlanActFlowConfig, e.g. container.build_agent_runner():
from weebot.application.services.code_reviewer_service import CodeReviewerService
from weebot.config.model_refs import MODEL_CODE_REVIEW

reviewer_llm = container.get_llm(model=MODEL_CODE_REVIEW)
code_reviewer = CodeReviewerService(llm=reviewer_llm, timeout_seconds=8.0)

config = PlanActFlowConfig(
    ...
    code_reviewer=code_reviewer,
)
```

### Feature toggle
The reviewer can be disabled per-run by passing `code_reviewer=None` to
`PlanActFlowConfig`. For convenience, it can also be gated via `task_preset`:

```python
# In executing.py _is_code_step gate (optional enhancement):
_cr_enabled = getattr(
    getattr(context, "_task_preset", None),
    "enable_code_review", True,
)
if _cr_enabled and getattr(context, "_code_reviewer", None) is not None ...:
    context.set_state(ReviewingState(...))
```

This mirrors how `enable_step_validation` gates `StepResultValidator`.

### CLI visibility
`ReviewingState.execute()` yields a `ThoughtEvent`. The CLI renderer already handles
`ThoughtEvent` — no UI changes needed. Web socket clients will see a "reviewing" status
update via `AgentStatus.REVIEWING` which `set_state()` broadcasts.

### Metrics / observability
`StructuredLogger.log_state_transition()` is called by `PlanActFlow.set_state()`.
`AgentStatus.REVIEWING` will appear in any Prometheus/OpenTelemetry dashboards already
scraping state transitions, with zero additional wiring.

---

## 7. Implementation Order

Execute the phases in this exact order to respect the dependency graph:

```
Phase 1  weebot/domain/models/code_review.py           (no deps)
Phase 2  weebot/application/ports/code_reviewer_port.py (depends on Phase 1)
Phase 3  weebot/application/services/code_reviewer_service.py (depends on Phase 2)
Phase 4  weebot/application/flows/states/base.py         (no deps — enum only)
Phase 5  weebot/application/flows/states/reviewing.py    (depends on Phase 1, 2, 4)
Phase 6  weebot/application/models/plan_act_flow_config.py (no structural dep)
Phase 7  weebot/application/flows/plan_act_flow.py       (depends on Phase 6)
Phase 8  weebot/application/flows/states/executing.py    (depends on Phase 5)
Phase 9  tests/unit/test_code_reviewer_service.py        (depends on Phase 3)
Phase 10 tests/unit/test_reviewing_state.py              (depends on Phase 5)
```

Each phase compiles independently — you can run `pytest` after Phase 3 and after
Phase 5 to get early feedback before wiring into the flow.

---

## 8. Invariants to Preserve

These must hold after the implementation:

1. **Backward compatibility**: `PlanActFlowConfig(code_reviewer=None)` (the default)
   produces identical behaviour to the pre-feature flow. No existing tests break.

2. **Fail-open**: any exception inside `CodeReviewerService.review()` returns
   `CodeReviewResult(verdict="approved")`. The flow must never stall on a reviewer crash.

3. **No infinite loops**: `_MAX_REVIEW_RETRIES = 2` in `ReviewingState` and
   `_MAX_REVIEW_RETRIES_GATE = 2` in `executing.py` must be equal. If they diverge the
   gate and the state disagree and a loop becomes possible.

4. **Immutability**: `Step` and `Plan` are always mutated via `model_copy()` /
   `replace_step()` / `update_step_status()`. Never assign to `.status` directly.

5. **Cross-lab diversity**: `MODEL_CODE_REVIEW = "x-ai/grok-4.3"` (xAI) is already a
   different lab from the executor's primary `"qwen/qwen3-coder:free"` (Alibaba/Qwen).
   The diversity principle from `ROLE_MODEL_CONFIG` is naturally satisfied.

6. **Domain purity**: `code_review.py` in the domain layer must not import from
   `application` or `infrastructure`. `CodeReviewerPort` in the application layer imports
   from domain only.

---

## 9. Estimated Scope

| Category | Lines |
|----------|-------|
| New production code | ~250 |
| New test code | ~150 |
| Edits to existing files | ~35 |
| **Total** | **~435** |

All 10 phases are independent enough that a single developer can implement and test
each in ~30 minutes. Total estimated implementation time: 4–5 hours.
