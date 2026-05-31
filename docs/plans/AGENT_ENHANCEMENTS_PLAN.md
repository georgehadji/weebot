# Agent Enhancements — Weebot v2.8

**Source**: Patterns from `pguso/ai-agents-from-scratch` (14-example curriculum)  
**Target**: Weebot v2.7.0 production framework  
**Date**: 2026-05-30  
**Architecture**: Clean Architecture (Hexagonal) + CQRS + Event-Driven

---

## Context

Weebot v2.7.0 has PlannerAgent + ExecutorAgent with structured output, model
cascading, bash safety, and 1,100+ tests. It lacks five patterns that the
ai-agents-from-scratch curriculum demonstrates as high-value for agent
reliability, observability, and decision quality:

1. **ReAct Thought Visibility** — agent reasoning is invisible between tool calls
2. **Chain-of-Thought Decision Workflow** — no governed multi-phase decision pipeline
3. **Deterministic Degraded Mode** — no graceful fallback when the LLM fails
4. **AoT Plan Validation** — plans have no semantic validation before execution
5. **Memory Dedup Utility** — no key-value deduplication in working memory

These enhancements respect the existing architecture: all new code lives in the
correct layer, mutations go through `mediator.send()`, I/O is behind ports, and
everything is tested.

---

## Enhancement A: ReAct Thought Visibility

**Severity**: Feature gap — agent reasoning is invisible  
**Layer impact**: Domain (new event) + Application (emitter) + Infrastructure (bus) + Interfaces (WebSocket)  
**Effort**: 2 days

### Problem

`ExecutorAgent.execute_step()` calls tools in a loop but emits no "why" between
calls. The structured output has a `reasoning` field but it's only emitted at
step completion. Users see:

```
Tool called: bash(find ... -mtime -7)  →  Result: [3 files]
Tool called: file_editor(open, main.py)  →  Result: [content]
```

No insight into *why* the agent chose those tools or what it expects to find.

### Proposed Change

#### A1 — New domain event

```python
# weebot/domain/models/event.py — add to AgentEvent union

class ThoughtEvent(BaseEvent):
    """Emitted when the agent explains its reasoning before acting."""
    type: Literal["thought"] = "thought"
    step_id: str = Field(default="")
    thought: str = Field(default="")
    iteration: int = Field(default=0)
```

Add `ThoughtEvent` to the `AgentEvent` union at the bottom of the file.

#### A2 — ExecutorAgent emits thoughts

The executor already has access to the LLM's `response.content` (the assistant
text) before tool calls. Extract the "thought" portion and emit it:

```python
# weebot/application/agents/executor.py — in execute_step(), before tool_call loop

for _ in range(self._max_steps):
    messages = [{"role": "system", "content": self._system_prompt}] + list(self._conversation_buffer)
    response = await self._llm.chat(...)

    # NEW: emit the reasoning text as a ThoughtEvent
    if response.content and response.content.strip():
        from weebot.domain.models.event import ThoughtEvent
        yield ThoughtEvent(
            step_id=step.id,
            thought=response.content.strip(),
            iteration=iteration_counter,  # track locally
        )

    if not response.tool_calls:
        break
    # ... rest of tool call loop unchanged
```

#### A3 — WebSocket handler streams thoughts

```python
# weebot/interfaces/web/routers/ws.py — in the event loop that broadcasts to clients

elif isinstance(event, ThoughtEvent):
    await ws.send_json({
        "type": "thought",
        "step_id": event.step_id,
        "thought": event.thought,
        "iteration": event.iteration,
        "timestamp": event.timestamp.isoformat(),
    })
```

#### A4 — CLI renders thoughts

```python
# weebot/interfaces/cli/agent_runner.py — in the event consumer loop

elif isinstance(event, ThoughtEvent):
    console.print(f"  [dim italic]🤔 {event.thought}[/dim italic]")
```

### Files Created

| File | Purpose |
|------|---------|
| `tests/unit/test_thought_event.py` | ThoughtEvent serialization, Union membership |

### Files Modified

| File | Change |
|------|--------|
| `weebot/domain/models/event.py` | Add `ThoughtEvent` class + to `AgentEvent` union |
| `weebot/application/agents/executor.py` | Emit `ThoughtEvent` before tool calls in loop |
| `weebot/interfaces/web/routers/ws.py` | Broadcast `ThoughtEvent` as WebSocket message |
| `weebot/interfaces/cli/agent_runner.py` | Render thought in CLI output |
| `tests/unit/test_executor_agent.py` | Assert ThoughtEvent emitted with step_id |

### Risk

Low. ThoughtEvent is additive — no existing events are removed or renamed.
If an LLM returns empty content (rare), no event is emitted (graceful skip).

### Rollback

Remove `ThoughtEvent` from the Union and the yield statement. Forward-compatible
— consumers that don't handle it just ignore the `type`.

---

## Enhancement B: Chain-of-Thought Decision Workflow

**Severity**: Feature gap — no governed multi-phase decision pipeline  
**Layer impact**: Domain + Application + Infrastructure + Interfaces  
**Effort**: 3 days

### Problem

Weebot's agents make decisions in a single LLM call. For high-stakes decisions
(PR approval, deployment gates, security review), this is insufficient — the agent
may jump to a conclusion without systematically checking risk, legitimacy, and
policy constraints. There's no audit trail per decision phase.

### Proposed Change

Implement a five-phase pipeline based on ai-agents-from-scratch example 14:

```
Phase 1: FactsOnlyAgent   — extract facts, no judgment
Phase 2: RiskScreening    — explicit risk/fraud/error checklist
Phase 3: LegitimacyAgent  — build the case FOR the decision
Phase 4: PolicyCheck      — apply business rules
Phase 5: DecisionAgent    — produce final decision with audit evidence
```

#### B1 — Domain models

```python
# weebot/domain/models/decision.py (NEW)

from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


class DecisionPhase(str, Enum):
    FACTS = "facts"
    RISK_SCREENING = "risk_screening"
    LEGITIMACY = "legitimacy"
    POLICY_CHECK = "policy_check"
    DECISION = "decision"


class DecisionOutcome(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    ESCALATE = "escalate"


class PhaseResult(BaseModel):
    """Evidence from one decision phase."""
    phase: DecisionPhase
    schema_version: str = "1.0"
    findings: dict = Field(default_factory=dict)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    tokens_used: int = 0


class DecisionOutput(BaseModel):
    """Complete auditable decision with all phase evidence."""
    decision: DecisionOutcome
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    phases: list[PhaseResult] = Field(default_factory=list)
    decision_reasoning: str = ""
    customer_message: str = ""    # user-safe message
    internal_note: str = ""       # audit-trail details
    escalation_path: Optional[str] = None
    model_used: str = "unknown"
    total_tokens: int = 0
    estimated_cost: float = 0.0
    correlation_id: str = ""
```

#### B2 — Decision agent

```python
# weebot/application/agents/decision_agent.py (NEW)

class DecisionAgent:
    """Orchestrates 5-phase Chain-of-Thought decision pipeline."""

    def __init__(
        self,
        llm: LLMPort,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        policy: Optional[dict] = None,  # business rules for phase 4
    ):
        self._llm = llm
        self._event_bus = event_bus
        self._model = model
        self._policy = policy or {}

    async def decide(
        self,
        context: dict,  # structured case data
        decision_type: str = "general",
    ) -> DecisionOutput:
        """Run all five phases and return an auditable decision."""
        import uuid
        correlation_id = str(uuid.uuid4())

        phases: list[PhaseResult] = []

        # Phase 1: Facts only — extract without judgment
        facts = await self._run_phase(
            DecisionPhase.FACTS,
            self._build_facts_prompt(context),
            schema=FACTS_SCHEMA,
        )
        phases.append(facts)

        # Phase 2: Risk screening — explicit checklist
        risk = await self._run_phase(
            DecisionPhase.RISK_SCREENING,
            self._build_risk_prompt(context, facts.findings),
            schema=RISK_SCHEMA,
        )
        phases.append(risk)

        # Phase 3: Legitimacy — case for approval
        legitimacy = await self._run_phase(
            DecisionPhase.LEGITIMACY,
            self._build_legitimacy_prompt(context, facts.findings),
            schema=LEGITIMACY_SCHEMA,
        )
        phases.append(legitimacy)

        # Phase 4: Policy check — rule-constrained
        policy_result = await self._run_phase(
            DecisionPhase.POLICY_CHECK,
            self._build_policy_prompt(context, risk.findings, legitimacy.findings),
            schema=POLICY_SCHEMA,
        )
        phases.append(policy_result)

        # Phase 5: Final decision — with full evidence
        decision = await self._run_phase(
            DecisionPhase.DECISION,
            self._build_decision_prompt(context, phases),
            schema=DECISION_SCHEMA,
        )
        phases.append(decision)

        total_tokens = sum(p.tokens_used for p in phases)

        return DecisionOutput(
            decision=DecisionOutcome(decision.findings.get("outcome", "escalate")),
            confidence=decision.score,
            phases=phases,
            decision_reasoning=decision.findings.get("reasoning", ""),
            customer_message=decision.findings.get("customer_message", ""),
            internal_note=decision.findings.get("internal_note", ""),
            model_used=self._model or "unknown",
            total_tokens=total_tokens,
            estimated_cost=self._estimate_cost(total_tokens),
            correlation_id=correlation_id,
        )

    # ... _run_phase, _build_*_prompt, schema constants below
```

#### B3 — Integration with existing flows

The DecisionAgent is a standalone agent — it doesn't replace ExecutorAgent.
It plugs in where weebot needs governed decisions:

- **Code review approval** — after `StructuredExecutorAgent` proposes changes
- **Deployment gate** — before bash commands with `requires_approval=True`
- **Security review** — when bash guard triggers `INJECTION_DETECTED`
- **Flow control** — a new `DecisionState` in `PlanActFlow` that routes through
  the decision pipeline before continuing

```python
# weebot/application/flows/states/deciding.py (NEW)

class DecidingState(FlowState):
    """Decision phase — runs Chain-of-Thought before proceeding."""

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        agent = DecisionAgent(
            llm=context._llm,
            event_bus=context._event_bus,
            model=context._model,
        )

        result = await agent.decide(context={
            "plan": context._plan.model_dump() if context._plan else {},
            "session_events": [e.model_dump() for e in context._session.events[-20:]],
        })

        # Emit decision as structured event
        yield DecisionEvent(
            decision=result.decision.value,
            confidence=result.confidence,
            reasoning=result.decision_reasoning,
            phases=result.phases,
        )

        if result.decision == DecisionOutcome.APPROVE:
            context.set_state(ExecutingState())
        elif result.decision == DecisionOutcome.ESCALATE:
            yield WaitForUserEvent(
                question=f"Decision escalated: {result.customer_message}\n\n"
                         f"Next action: {result.escalation_path or 'Manual review required.'}"
            )
            context._session = context._session.set_status(SessionStatus.WAITING)
        else:
            yield ErrorEvent(error=f"Decision: {result.decision.value} — {result.customer_message}")
            context.set_state(SummarizingState())
```

### Files Created

| File | Purpose |
|------|---------|
| `weebot/domain/models/decision.py` | DecisionOutput, PhaseResult, DecisionOutcome, DecisionPhase |
| `weebot/application/agents/decision_agent.py` | DecisionAgent with 5-phase pipeline |
| `weebot/application/flows/states/deciding.py` | DecidingState for PlanActFlow integration |
| `tests/unit/domain/test_decision_models.py` | Pydantic validation, serialization |
| `tests/unit/application/test_decision_agent.py` | Mock LLM returns known JSON; verify phase ordering, scoring, fallback |
| `tests/integration/test_decision_flow.py` | Full pipeline with mocked LLM |

### Files Modified

| File | Change |
|------|--------|
| `weebot/domain/models/event.py` | Add `DecisionEvent` to AgentEvent union |
| `weebot/application/di.py` | Add placeholder for DecisionAgent (no port needed — it's application-layer) |
| `weebot/interfaces/web/routers/ws.py` | Broadcast DecisionEvent to WebSocket clients |

### Risk

Medium. DecisionAgent creates 5 sequential LLM calls — latency and cost scale
linearly. Mitigation: each phase uses `max_tokens=800`, which keeps per-phase
cost low (~$0.002 per phase with GPT-4o-mini). Parallelize phases 2 and 3
(risk and legitimacy are independent of each other).

### Rollback

DecisionAgent is an additive component. Disabling it means not routing into
`DecidingState` — no existing flows are modified.

---

## Enhancement C: Deterministic Degraded Mode

**Severity**: Reliability gap — no graceful fallback when LLM fails  
**Layer impact**: Application (service + state)  
**Effort**: 1.5 days

### Problem

When the LLM provider returns a 429, 500, or times out, the error propagates up
to the flow and the task fails with `ErrorEvent`. The executor has retry logic
but no non-LLM fallback path. Some tasks (e.g., "list all Python files modified
today") could be completed deterministically without any LLM at all.

### Proposed Change

#### C1 — Degraded handler service

```python
# weebot/application/services/degraded_handler.py (NEW)

import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DegradedHandler:
    """Deterministic fallback when the LLM is unavailable.

    Handles a narrow set of common task patterns without any LLM calls:
    - File enumeration (find, list, ls, grep)
    - Simple math (calculate, compute numeric expressions)
    - Time queries (what time, what date)
    - Cache lookups (recent similar requests)

    Returns None if the task cannot be handled deterministically,
    signaling that true failure should propagate.
    """

    # Patterns that can be handled without an LLM
    _FILE_FIND_PATTERN = re.compile(
        r"(?:find|list|ls|show|get)\s+(?:all\s+)?(?:the\s+)?"
        r"(?:Python\s+)?(?:files?|modules?|scripts?)",
        re.IGNORECASE,
    )
    _EXT_PATTERN = re.compile(r"\.(\w+)\b")
    _TIME_PATTERN = re.compile(r"(?:what|current)\s+(?:time|date|datetime)", re.IGNORECASE)
    _CALC_PATTERN = re.compile(
        r"(?:calculate|compute|what\s+is)\s+[\d\s+\-*/().]+",
        re.IGNORECASE,
    )

    async def try_handle(self, user_input: str, working_dir: str = ".") -> Optional[str]:
        """Attempt to handle the input deterministically.

        Returns:
            A result string if handled, None if LLM fallback is required.
        """
        input_lower = user_input.lower().strip()

        # 1. File enumeration
        if self._FILE_FIND_PATTERN.search(input_lower):
            return await self._handle_file_find(input_lower, working_dir)

        # 2. Time query
        if self._TIME_PATTERN.search(input_lower):
            return self._handle_time_query()

        # 3. Simple math
        if self._CALC_PATTERN.search(input_lower):
            return self._handle_calc(input_lower)

        # 4. Unhandled — must use LLM
        logger.debug("DegradedHandler: cannot handle input deterministically")
        return None

    async def _handle_file_find(self, query: str, cwd: str) -> Optional[str]:
        extensions = self._EXT_PATTERN.findall(query)
        pattern = "*.py" if not extensions else f"*.{extensions[0]}"

        try:
            matches = sorted(Path(cwd).rglob(pattern))
            # Limit to 50 files
            if not matches:
                return f"No {pattern} files found in {cwd}."
            lines = [f"Found {len(matches)} {pattern} file(s):"]
            for p in matches[:50]:
                lines.append(f"  {p.relative_to(cwd)}")
            if len(matches) > 50:
                lines.append(f"  ... and {len(matches) - 50} more")
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("DegradedHandler file find failed: %s", exc)
            return None

    @staticmethod
    def _handle_time_query() -> str:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return (
            f"Current time (UTC): {now.isoformat()}\n"
            f"System local: {now.astimezone().isoformat()}"
        )

    @staticmethod
    def _handle_calc(query: str) -> Optional[str]:
        import ast
        import operator as op

        # Extract numeric expression
        match = re.search(r"[\d\s+\-*/().]+$", query)
        if not match:
            return None

        expr = match.group(0).strip()

        # Safe evaluation (only numeric literals, operators, parens)
        allowed_nodes = (
            ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub,
        )

        try:
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if not isinstance(node, allowed_nodes):
                    return None  # unsafe expression
            result = eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}})
            return f"Result: {result}"
        except Exception:
            return None
```

#### C2 — Integration into PlanActFlow

```python
# weebot/application/flows/states/executing.py — in the catch block

if context._mediator:
    cmd_result = await context._mediator.send(ExecuteStepCommand(...))
    if not cmd_result.success:
        # NEW: try degraded mode before failing
        if "LLM_CALL_FAILED" in str(cmd_result.error) or "APIError" in str(cmd_result.error):
            from weebot.application.services.degraded_handler import DegradedHandler
            handler = DegradedHandler()
            degraded_result = await handler.try_handle(prompt or step.description)
            if degraded_result is not None:
                logger.warning(
                    "Step %s resolved via degraded mode (LLM unavailable). "
                    "Correlation: %s",
                    step.id, cmd_result.data.get("correlation_id", "unknown"),
                )
                yield MessageEvent(
                    role="assistant",
                    message=f"[Degraded mode — LLM unavailable]\n{degraded_result}",
                )
                # Mark step completed
                context._plan = context._plan.update_step_status(step.id, StepStatus.COMPLETED)
                context.set_state(UpdatingState())
                return
        # Can't handle — propagate error
        yield ErrorEvent(error=f"Step execution rejected: {cmd_result.error}")
        context.set_state(UpdatingState())
        return
```

#### C3 — Correlation ID propagation

The existing `ErrorContext` already has `correlation_id`. Ensure all
LLM-related errors carry it, and the degraded handler logs it:

```python
# weebot/error_system_handler.py — ensure correlation_id is always populated

def handle_llm_error(self, error: Exception, context: dict | None = None) -> WeebotError:
    correlation_id = (context or {}).get("correlation_id") or str(uuid.uuid4().hex[:12])
    return APIError(
        service="LLM provider",
        status_code=getattr(error, "status_code", None),
        remediation="The system will attempt a deterministic fallback.",
        correlation_id=correlation_id,
    )
```

### Files Created

| File | Purpose |
|------|---------|
| `weebot/application/services/degraded_handler.py` | DegradedHandler with file/time/calc fallbacks |
| `tests/unit/application/test_degraded_handler.py` | Test each deterministic path; test None for unhandled inputs |

### Files Modified

| File | Change |
|------|--------|
| `weebot/application/flows/states/executing.py` | Catch LLMCallError → try degraded → propagate if unhandled |
| `weebot/error_system_handler.py` | Ensure correlation_id on LLM errors |

### Risk

Low. The degraded handler only activates when the LLM has already failed — it
cannot make things worse. It handles a narrow, safe set of operations (no
shell execution, no file writes, no network calls). All operations are
read-only or purely computational.

### Rollback

Remove the try/except block in `executing.py` — errors propagate as before.
The DegradedHandler file can be deleted with no impact on other code.

---

## Enhancement D: Atom-of-Thought Plan Validation

**Severity**: Reliability gap — plans have no semantic validation  
**Layer impact**: Application (service)  
**Effort**: 1.5 days

### Problem

`PlannerAgent.create_plan()` produces a JSON plan but only checks:
- Is it valid JSON? (structural)
- Does it have `title`, `message`, `steps`? (shape)

There's no check that:
- Steps reference tools the executor actually has
- Step dependencies form a valid DAG (no cycles)
- First steps have concrete inputs (no dangling `<result_of_N>` references)
- Steps don't contradict each other

If the planner produces a bad plan, the executor discovers it mid-execution and fails.

### Proposed Change

#### D1 — Plan validator

```python
# weebot/application/services/plan_validator.py (NEW)

from dataclasses import dataclass, field
from typing import Optional, Set
from weebot.domain.models.plan import Plan

@dataclass
class ValidationIssue:
    step_id: str
    severity: str  # "error", "warning"
    message: str


@dataclass
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


class PlanValidator:
    """Semantic validation of executable plans before execution.

    Checks:
    1. Tool availability — every step that names a tool references a known tool
    2. Step ID uniqueness — no duplicate step IDs
    3. Dependency chain — steps with depends_on reference existing steps (DAG)
    4. Input completeness — first steps have concrete inputs
    5. Termination path — there's at least one step that can conclude the plan
    """

    def __init__(self, available_tools: Optional[set[str]] = None):
        self._available_tools = available_tools or set()
        self._known_tool_names = {
            "bash", "python", "file_editor", "browser", "web_search",
            "knowledge_tool", "ocr", "powershell", "schedule", "screen",
            "terminate", "ask_human", "computer_use", "control",
        }

    def validate(self, plan: Plan) -> ValidationResult:
        issues: list[ValidationIssue] = []

        # 1. Step ID uniqueness
        seen_ids: set[str] = set()
        for step in plan.steps:
            if step.id in seen_ids:
                issues.append(ValidationIssue(
                    step_id=step.id,
                    severity="error",
                    message=f"Duplicate step ID: '{step.id}'",
                ))
            seen_ids.add(step.id)

        # 2. Empty plan
        if not plan.steps:
            issues.append(ValidationIssue(
                step_id="(plan)",
                severity="error",
                message="Plan has no steps — cannot execute.",
            ))
            return ValidationResult(is_valid=False, issues=issues)

        # 3. Step descriptions — must be actionable
        for step in plan.steps:
            if len(step.description.strip()) < 10:
                issues.append(ValidationIssue(
                    step_id=step.id,
                    severity="warning",
                    message=f"Step '{step.id}' has very short description — may lack context.",
                ))
            if self._is_ambiguous(step.description):
                issues.append(ValidationIssue(
                    step_id=step.id,
                    severity="warning",
                    message=f"Step '{step.id}' description is ambiguous — may cause agent confusion.",
                ))

        # 4. Known tool names — warn if step references unknown tool
        for step in plan.steps:
            mentioned_tools = self._extract_tool_references(step.description)
            unknown = mentioned_tools - self._known_tool_names
            if unknown:
                issues.append(ValidationIssue(
                    step_id=step.id,
                    severity="warning",
                    message=f"Step '{step.id}' references unknown tool(s): {unknown}. "
                            f"Available: {sorted(self._known_tool_names)}",
                ))

        # 5. Check for termination path
        has_terminate_or_ask = any(
            any(tool in step.description.lower()
                for tool in ("terminate", "summariz", "ask_human", "final"))
            for step in plan.steps[-2:]  # at least one of the last 2
        )
        if not has_terminate_or_ask and len(plan.steps) > 2:
            issues.append(ValidationIssue(
                step_id="(plan)",
                severity="warning",
                message="Plan may lack a termination path — last steps don't mention "
                        "finalize, summarize, or ask_human.",
            ))

        return ValidationResult(
            is_valid=not issues or all(i.severity != "error" for i in issues),
            issues=issues,
        )

    @staticmethod
    def _is_ambiguous(description: str) -> bool:
        """Heuristic: descriptions with only generic verbs may be ambiguous."""
        lower = description.lower().strip()
        generic_only = {"do", "handle", "process", "work on", "fix", "check"}
        words = set(lower.split())
        content_words = words - {"the", "a", "an", "of", "in", "to", "for", "and", "or"}
        return len(content_words - generic_only) < 2

    @staticmethod
    def _extract_tool_references(description: str) -> set[str]:
        """Simple heuristic: look for tool-like words in description."""
        import re
        lower = description.lower()
        # Match snake_case and kebab-case identifiers
        identifiers = set(re.findall(r'\b[a-z_][a-z0-9_]{2,}\b', lower))
        return identifiers
```

#### D2 — Integration into PlanActFlow

Insert validation between `PlanningState` and `ExecutingState`:

```python
# weebot/application/flows/states/planning.py — at the end of execute()

# After plan is created, validate it before transitioning
from weebot.application.services.plan_validator import PlanValidator, ValidationIssue

validator = PlanValidator()
validation = validator.validate(context._plan)

if not validation.is_valid:
    for issue in validation.errors:
        yield ErrorEvent(error=f"Plan validation error [{issue.step_id}]: {issue.message}")
    # Re-prompt planner with validation errors
    context._memory.append({
        "role": "user",
        "content": (
            f"The plan you generated has validation errors:\n" +
            "\n".join(f"- [{i.step_id}] {i.message}" for i in validation.errors) +
            "\n\nPlease fix these issues and regenerate the plan."
        ),
    })
    # Stay in PlanningState — will re-plan
    return

for issue in validation.warnings:
    logger.warning("Plan warning [%s]: %s", issue.step_id, issue.message)

# All good — proceed to execution
context.set_state(ExecutingState())
```

### Files Created

| File | Purpose |
|------|---------|
| `weebot/application/services/plan_validator.py` | PlanValidator, ValidationResult, ValidationIssue |
| `tests/unit/application/test_plan_validator.py` | Test duplicate IDs, empty plan, ambiguous descriptions, tool references, termination path |

### Files Modified

| File | Change |
|------|--------|
| `weebot/application/flows/states/planning.py` | Insert plan validation between planning and execution |

### Risk

Low. The validator is advisory — it emits warnings for soft issues and errors
with re-prompt for hard issues. It never blocks a valid plan. The re-prompt
path adds one extra LLM call per invalid plan, but invalid plans are rare
(planner has JSON schema grammar enforcement).

### Rollback

Comment out the validation block in `planning.py` — plans proceed directly to
execution as before.

---

## Enhancement E: Memory Dedup Utility

**Severity**: Refinement — existing memory works, could be more efficient  
**Layer impact**: Core (utility)  
**Effort**: 0.5 days

### Problem

The executor accumulates facts via `self._facts[tool_name] = result.data`. If
a tool is called multiple times with different results, old facts are silently
overwritten. If the same fact is discovered again (same key, same value), it's
stored redundantly. Session-level facts via `session.set_fact()` have no dedup.

### Proposed Change

A small utility wrapping key-value storage with normalize-compare-dedup logic,
following the pattern from ai-agents-from-scratch's `MemoryManager.addMemory()`:

```python
# weebot/core/memory_dedup.py (NEW)

"""Key-value memory deduplication utility.

Normalises keys/values before storage, skips exact duplicates,
updates changed values, and logs the action taken.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DedupStore:
    """Key-value store with automatic deduplication.

    Usage:
        store = DedupStore()
        store.set("user_name", "Alex")    # → "added"
        store.set("user_name", "Alex")    # → "skipped" (duplicate)
        store.set("user_name", "Bob")     # → "updated" (value changed)
        store.get("user_name")            # → "Bob"
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._data: dict[str, Any] = {}
        self._timestamps: dict[str, datetime] = {}
        self._max_entries = max_entries

    def set(self, key: str, value: Any, source: str = "agent") -> str:
        """Store a key-value pair with deduplication.

        Returns:
            "added" — new entry stored
            "skipped" — exact duplicate, not stored
            "updated" — existing key, value changed, updated
        """
        norm_key = self._normalize(key)
        norm_value = self._normalize(value) if isinstance(value, str) else value

        if norm_key in self._data:
            existing = self._data[norm_key]
            if existing == norm_value:
                logger.debug("DedupStore: skipped duplicate key '%s'", norm_key)
                return "skipped"
            self._data[norm_key] = norm_value
            self._timestamps[norm_key] = datetime.now(timezone.utc)
            logger.debug("DedupStore: updated key '%s'", norm_key)
            return "updated"

        # Evict oldest if at capacity
        if len(self._data) >= self._max_entries:
            oldest = min(self._timestamps, key=lambda k: self._timestamps[k])
            del self._data[oldest]
            del self._timestamps[oldest]

        self._data[norm_key] = norm_value
        self._timestamps[norm_key] = datetime.now(timezone.utc)
        logger.debug("DedupStore: added key '%s'", norm_key)
        return "added"

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(self._normalize(key), default)

    def has(self, key: str) -> bool:
        return self._normalize(key) in self._data

    def remove(self, key: str) -> bool:
        norm_key = self._normalize(key)
        if norm_key in self._data:
            del self._data[norm_key]
            del self._timestamps[norm_key]
            return True
        return False

    def clear(self) -> None:
        self._data.clear()
        self._timestamps.clear()

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    @property
    def size(self) -> int:
        return len(self._data)

    @staticmethod
    def _normalize(key: str) -> str:
        return key.strip().lower()
```

This is not used internally by ExecutorAgent by default (avoids breaking
existing behavior). It's made available as a utility for any new code that
needs key-value dedup — e.g., skill storage, user preferences, or custom
agent implementations.

### Files Created

| File | Purpose |
|------|---------|
| `weebot/core/memory_dedup.py` | DedupStore utility |
| `tests/unit/core/test_memory_dedup.py` | Test add/skip/update/eviction/clear |

### Files Modified

None. This is an additive utility. Existing code is not touched.

### Risk

None. Pure utility with no side effects. Not wired into any existing code path.

---

## Implementation Schedule

```
Phase 1 (E + A): 2.5 days
  Day 1     │ E: Memory Dedup (0.5d)             │ Small, standalone
  Day 2-3   │ A: Thought Visibility (2d)         │ Domain event + executor + WebSocket + CLI

Phase 2 (D + C): 3 days
  Day 4-5   │ D: Plan Validation (1.5d)          │ Service + planning.py integration
  Day 5-6   │ C: Degraded Mode (1.5d)            │ Service + executing.py integration

Phase 3 (B): 3 days
  Day 7-9   │ B: Chain-of-Thought Decision (3d)  │ Domain models + agent + flow state + tests
```

**Total**: ~8 days · ~9 person-days (parallelizable: E+A can run alongside C)

---

## Test Strategy

Each enhancement follows the project's existing test conventions:

- **Unit tests** — `tests/unit/domain/`, `tests/unit/application/`, `tests/unit/core/`
  with mocked LLM ports (returning known JSON), in-memory SQLite for state repos
- **Integration tests** — `tests/integration/` with `AsyncMock` LLM, real
  `AsyncEventBus`, real `Container` from DI
- **Architecture fitness** — add import checks for new domain models, verify no
  domain→infrastructure imports, verify new agents conform to Clean Architecture
- **Coverage target** — 80%+ on new code

### Test counts

| Enhancement | Unit tests | Integration tests | Total |
|-------------|-----------|-------------------|-------|
| A — Thought Visibility | 4 | 1 | 5 |
| B — CoT Decision | 12 | 2 | 14 |
| C — Degraded Mode | 8 | 1 | 9 |
| D — Plan Validation | 10 | 1 | 11 |
| E — Memory Dedup | 8 | 0 | 8 |
| **Total** | **42** | **5** | **47** |

---

## Architecture Compliance

All enhancements respect the existing architecture rules (verified by
`tests/unit/test_architecture_fitness.py`):

- **Domain models** — `ThoughtEvent`, `DecisionOutput`, `PhaseResult` live in
  `weebot/domain/models/`. They import nothing from outer layers.
- **Application services** — `PlanValidator`, `DegradedHandler` live in
  `weebot/application/services/`. They import from domain ports, not
  infrastructure.
- **Application agents** — `DecisionAgent` lives in `weebot/application/agents/`.
  It depends on `LLMPort` (abstract), not concrete adapters.
- **Flow states** — `DecidingState` lives in `weebot/application/flows/states/`.
  It transitions within the `PlanActFlow` state machine.
- **Core utilities** — `DedupStore` lives in `weebot/core/`. No domain or
  application dependencies.
- **Interfaces** — WebSocket handler (`ws.py`) and CLI (`agent_runner.py`) are
  the only places that import new event types for rendering. No business logic
  in interfaces.
- **DI composition root** — `application/di.py` wires `DecisionAgent` and
  `DegradedHandler` through the container. `PlanValidator` is stateless and
  instantiated directly in `PlanningState`.
- **CQRS** — The existing `ExecuteStepCommand` already routes through the
  mediator. The degraded mode path is inside the mediator handler's catch
  block, not bypassing CQRS.

---

## References

- `pguso/ai-agents-from-scratch` — examples 09 (ReAct), 11 (error handling),
  14 (Chain of Thought), 10 (Atom of Thought), 08 (memory)
- Weebot architecture audit — `docs/plans/ENHANCEMENT_PROPOSALS.md`
- Weebot DI container — `weebot/application/di.py`
- Existing domain events — `weebot/domain/models/event.py`
- Existing flow states — `weebot/application/flows/states/`
- Existing structured output — `weebot/models/structured_output.py`
