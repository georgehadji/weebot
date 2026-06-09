# Reasoner-Inspired Enhancements — Implementation Plan

**Status:** Draft  
**Target branch:** `feature/reasoner-enhancements`  
**Architecture baseline:** Clean Hexagonal (Interfaces → Infrastructure → Application → Domain)  
**Fitness gate:** `pytest tests/unit/test_architecture_fitness.py` must stay green after every phase  
**Source research:** `E:\Documents\Vibe-Coding\Reasoner` — patterns from `hypergate/`, `application/flows/`, `quality/`, `domain/preset_registry.py`, `neuro/`

---

## 1. Motivation

Research into the Reasoner project identified 8 confirmed gaps in weebot's
planning and execution pipeline. Items already covered by weebot
(`CritiquingState`, `VerifyingState`, `MetaAnalysisState`, `MixtureOfAgentsTool`)
are excluded. Every item below was verified against the actual weebot source
before inclusion.

| # | Enhancement | Impact | Complexity |
|---|-------------|--------|------------|
| 1 | Parallel multi-agent pre-router | High — eliminates planning overhead for ~40% of tasks | Medium |
| 2 | Pre-mortem reasoning state | High — proactive failure prevention before execution | Low |
| 3 | Cross-lab model diversity | High — reduces echo-chamber blind spots in plan critique | Low |
| 4 | Declarative task complexity presets | High — cost/quality tiers without touching flow logic | Medium |
| 5 | Tree-of-Thoughts plan revision | Medium — escapes local-minimum revision loops | High |
| 6 | Step-result quality monitoring | Medium — catches poor-quality non-error step outputs | Medium |
| 7 | UpdatingState quality hints | Low-Medium — one-line reuse of existing critic | Low |
| 8 | Hot/warm/cold memory lifecycle | Low — prevents unbounded growth of memory files | Medium |

---

## 2. Architecture Constraints

All changes must satisfy `tests/unit/test_architecture_fitness.py`:

- **Domain pure:** `weebot/domain/` must not import from Application or Infrastructure
- **Application no module-level infra:** Infrastructure imports only inside functions or `TYPE_CHECKING` blocks
- **Tools no sqlite3:** `weebot/tools/` must not import `sqlite3`, `aiosqlite`, `sqlalchemy`
- **No flat files at `weebot/` root**
- **Ports need adapters:** Every new `weebot/application/ports/` entry needs a registered adapter in DI
- **No circular imports**

Layer placement for new files:

| What | Where |
|------|-------|
| New flow state | `weebot/application/flows/states/` |
| New application service | `weebot/application/services/` |
| New domain model | `weebot/domain/models/` |
| New domain config (presets) | `weebot/config/` (not domain — avoids adding dependency on config from domain) |
| New port | `weebot/application/ports/` + adapter in `weebot/infrastructure/` + DI entry |
| Model cascade extension | `weebot/core/model_cascade_config.py` (existing) |
| DI wiring | `weebot/application/di/_factories.py` + `weebot/application/di/__init__.py` |

---

## 3. Phase Overview

```
Phase 1  Pre-mortem state             (new state, no dependencies, lowest risk)
Phase 2  UpdatingState quality hints  (one-line change, reuses existing critic)
Phase 3  Step-result quality monitor  (new validator service + executor change)
Phase 4  Cross-lab model diversity    (config + selector, no flow changes)
Phase 5  Declarative task presets     (new domain model + config registry)
Phase 6  Parallel multi-agent router  (replaces KeywordTaskRouter, biggest change)
Phase 7  Tree-of-Thoughts revision    (new scorer + UpdatingState rework)
Phase 8  Memory lifecycle             (new service, purely additive)
```

Phases 1–4 are independent and can proceed in parallel.  
Phase 5 depends on Phase 4 (presets reference role models).  
Phase 6 depends on Phase 5 (router uses preset selection).  
Phases 7 and 8 are independent of the rest.

---

## 4. Phase 1 — Pre-Mortem Reasoning State

### 4.1 Goal

Before `ExecutingState`, ask the LLM to imagine the plan has already failed and
identify the most likely causes. The output is injected back into the plan as
explicit risk-mitigation notes, converting reactive `UpdatingState` corrections
into proactive plan improvements.

### 4.2 New Files

| File | Purpose |
|------|---------|
| `weebot/application/flows/states/premortem.py` | New `PremortmState` flow state |
| `weebot/application/services/premortem_analyzer.py` | LLM call + result parsing |
| `tests/unit/test_premortem_state.py` | Unit tests |

### 4.3 `PremortmAnalyzer` — `weebot/application/services/premortem_analyzer.py`

```python
"""PremortmAnalyzer — prospective failure analysis before plan execution.

Implements the Gary Klein pre-mortem methodology: ask the LLM to imagine
the plan has already failed and surface likely failure causes.  The output
is a list of risk strings injected into the plan as notes.

Design notes:
- Uses budget-tier model (cheap, fast, non-critical path).
- On timeout or parse failure, returns an empty list (non-blocking).
- 3 risks max — enough signal without bloating the plan.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort
    from weebot.domain.models.plan import Plan

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a pre-mortem analyst. Imagine it is 3 months from now
and the plan below has completely failed. Reason backwards: what went wrong?

Focus on concrete, specific failure modes — not vague advice.

Return ONLY valid JSON (no markdown, no fences):
{"risks": ["risk 1", "risk 2", "risk 3"]}

Maximum 3 risks, each under 100 characters."""

_MAX_RISKS = 3
_TIMEOUT_SECONDS = 8.0


class PremortmAnalyzer:
    """Runs a pre-mortem analysis on a plan and returns a list of risk strings."""

    def __init__(self, llm: "LLMPort", timeout_seconds: float = _TIMEOUT_SECONDS) -> None:
        self._llm = llm
        self._timeout = timeout_seconds

    async def analyze(self, plan: "Plan", task: str) -> list[str]:
        """Return up to 3 prospective failure causes for *plan*.

        On timeout or parse failure, returns [] so the flow is never blocked.
        """
        try:
            import asyncio
            steps_text = "\n".join(
                f"  {i+1}. {s.description}" for i, s in enumerate(plan.steps)
            )
            user_msg = (
                f"Task: {task}\n\nPlan:\n{steps_text}\n\n"
                "What are the most likely causes of failure?"
            )
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.4,
                    max_tokens=200,
                ),
                timeout=self._timeout,
            )
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(raw)
            risks = [str(r) for r in data.get("risks", []) if r]
            return risks[:_MAX_RISKS]
        except Exception as exc:
            logger.debug("PremortmAnalyzer non-blocking failure: %s", exc)
            return []
```

### 4.4 `PremortmState` — `weebot/application/flows/states/premortem.py`

```python
"""PremortmState — prospective failure analysis before execution.

Sits between CritiquingState and ExecutingState when enabled.
Injects risk notes into the plan; never blocks execution.

Enabled by: plan step count >= PREMORTEM_MIN_STEPS (default 3)
OR task_preset.enable_premortem == True.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent, ThoughtEvent

logger = logging.getLogger(__name__)

PREMORTEM_MIN_STEPS = 3


class PremortmState(FlowState):
    """Runs a pre-mortem analysis and injects risk notes into the plan."""

    status = AgentStatus.PLANNING  # Planning sub-phase — reuses existing status

    async def execute(
        self, context: "PlanActFlow", prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.executing import ExecutingState
        from weebot.application.services.premortem_analyzer import PremortmAnalyzer

        plan = context._plan
        if plan is None or len(plan.steps) < PREMORTEM_MIN_STEPS:
            logger.debug(
                "Pre-mortem skipped: plan has %d steps (min %d)",
                len(plan.steps) if plan else 0, PREMORTEM_MIN_STEPS,
            )
            context.set_state(ExecutingState())
            return

        analyzer = PremortmAnalyzer(llm=context._llm)
        risks = await analyzer.analyze(plan, prompt)

        if risks:
            # Inject risk notes into plan message so PlannerAgent / executor can see them
            risk_block = "\n".join(f"⚠ {r}" for r in risks)
            context._plan = plan.model_copy(
                update={"message": f"{plan.message or ''}\n\n[Pre-mortem risks]\n{risk_block}".strip()}
            )
            logger.info("Pre-mortem injected %d risks into plan", len(risks))

            yield ThoughtEvent(
                step_id="premortem",
                thought=(
                    f"**Pre-Mortem Analysis** — {len(risks)} potential failure modes:\n\n"
                    + "\n".join(f"- {r}" for r in risks)
                ),
            )
        else:
            logger.debug("Pre-mortem produced no risks")

        context.set_state(ExecutingState())
```

### 4.5 Wire into `plan_act_flow.py`

In `CritiquingState.execute()`, change the "high confidence → proceed" branch:

```python
# Current (critiquing.py line 86):
context.set_state(ExecutingState())

# New:
from weebot.application.flows.states.premortem import PremortmState
context.set_state(PremortmState())
```

Also change the medium-confidence branch (line 96). Pre-mortem still runs;
the critique warnings are already stored on `context._plan_critique` and will
be picked up by the executor.

The "low confidence → PlanningState" branch is unchanged — pre-mortem only
runs on approved plans.

### 4.6 Tests — `tests/unit/test_premortem_state.py`

- `test_analyzer_returns_risks_on_valid_response` — mock LLM returns JSON; risks list has ≤ 3 items
- `test_analyzer_returns_empty_on_timeout` — mock LLM raises `asyncio.TimeoutError`; returns `[]`
- `test_analyzer_returns_empty_on_parse_failure` — mock LLM returns malformed JSON; returns `[]`
- `test_state_injects_risks_into_plan_message` — risks appear in `context._plan.message`
- `test_state_skips_short_plan` — plan with 2 steps transitions directly to `ExecutingState`
- `test_state_transitions_to_executing` — verify final `set_state(ExecutingState())` call

### 4.7 Risk: Low

Purely additive. `PremortmAnalyzer` never raises. `PremortmState` always
transitions to `ExecutingState` regardless of outcome. Worst case: 8s timeout
during which the agent appears to pause; mitigated by `asyncio.wait_for`.

---

## 5. Phase 2 — UpdatingState Quality Hints

### 5.1 Goal

When `UpdatingState` generates a revised plan, pass it through
`PlanCriticService` before transitioning back to `ExecutingState`. If the
revision scores below the warn threshold, inject the critique as a hint into
the executor prompt — exactly what `CritiquingState` already does for initial
plans.

### 5.2 Files Modified

| File | Change |
|------|--------|
| `weebot/application/flows/states/updating.py` | Add critic call after plan update |
| `weebot/application/flows/plan_act_flow.py` | Expose `_plan_critic` to `UpdatingState` |

### 5.3 Implementation — `updating.py`

After `context._plan = Plan.model_validate(...)` and `context._snapshot_plan()`,
add (before `context.set_state(ExecutingState())`):

```python
# ── Post-revision critique (reuses CritiquingState logic) ──────────────
if context._plan_critic is not None and context._plan is not None:
    critique_context = {
        "task": prompt,
        "tools": [t.name for t in context._tools] if hasattr(context._tools, "__iter__") else [],
    }
    critique = await context._plan_critic.critique(context._plan, critique_context)
    if critique.overall_confidence < ConfidentThresholds.WARN_THRESHOLD:
        # Store for executor prompt injection — same mechanism as CritiquingState
        context._plan_critique = critique
        logger.info(
            "Revised plan scored %.2f — critique injected as executor hint",
            critique.overall_confidence,
        )
    else:
        context._plan_critique = None  # Clear stale critique from previous cycle
```

Import `ConfidentThresholds` from `weebot.application.flows.states.critiquing`.

### 5.4 Tests — `tests/unit/test_updating_state_critic.py`

- `test_low_confidence_revision_stores_critique` — critic scores 0.4; `context._plan_critique` is set
- `test_high_confidence_revision_clears_critique` — critic scores 0.9; `context._plan_critique` is `None`
- `test_no_critic_is_noop` — `context._plan_critic = None`; `context._plan_critique` unchanged
- `test_critic_timeout_does_not_block_transition` — mock critic raises `asyncio.TimeoutError`; still transitions

### 5.5 Risk: Low

One-line call on the existing `PlanCriticService`. The critic already has a
built-in 5s timeout that falls back to "approved" — the flow can never be
blocked by this change.

---

## 6. Phase 3 — Step-Result Quality Monitoring

### 6.1 Goal

`ExecutingState` advances the plan when a step's `ToolResult` arrives. It
currently only checks for `is_error`. Add a lightweight quality check: if a
step returns a non-error result that is empty, suspiciously short, or a known
low-signal pattern, inject a quality hint and retry that step once before
advancing.

### 6.2 New Files

| File | Purpose |
|------|---------|
| `weebot/application/services/step_result_validator.py` | Rule-based + optional LLM check |
| `tests/unit/test_step_result_validator.py` | Unit tests |

### 6.3 `StepResultValidator` — `weebot/application/services/step_result_validator.py`

```python
"""StepResultValidator — lightweight quality gate on step outputs.

Two-tier: rule-based checks first (fast, free), optional LLM judge only
when rules detect a suspicious result.  Never blocks — on LLM failure,
returns ValidationResult(passed=True).

Rules:
  1. Empty output (len == 0) — always suspicious
  2. Too short (len < MIN_RESULT_CHARS) — suspicious for non-trivial steps
  3. Exact error strings wrapped in success (e.g. "None", "null", "undefined")
  4. Repetition: result == previous_result (step produced no new information)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_RESULT_CHARS = 20
_SUSPICIOUSLY_EMPTY = frozenset({"none", "null", "undefined", "n/a", "", "false", "[]", "{}"})


@dataclass
class ValidationResult:
    passed: bool
    reason: str = ""
    quality_hint: str = ""  # injected into retry prompt if not passed


class StepResultValidator:
    """Validates a step result before the executor advances to the next step."""

    def validate(
        self,
        result: str | None,
        step_description: str,
        previous_result: str | None = None,
    ) -> ValidationResult:
        """Run rule-based quality checks.

        Args:
            result: The string output of the completed step.
            step_description: Used to contextualise the quality hint.
            previous_result: Output of the same step on a previous attempt
                             (used to detect zero-information retries).

        Returns:
            ValidationResult(passed=True) when the result looks acceptable.
        """
        if result is None or result.strip().lower() in _SUSPICIOUSLY_EMPTY:
            return ValidationResult(
                passed=False,
                reason="step returned empty or null-equivalent output",
                quality_hint=(
                    f"The previous attempt for step '{step_description}' returned "
                    f"an empty or null result. Produce concrete, non-empty output."
                ),
            )

        if len(result.strip()) < MIN_RESULT_CHARS:
            return ValidationResult(
                passed=False,
                reason=f"result too short ({len(result.strip())} chars)",
                quality_hint=(
                    f"The previous attempt for step '{step_description}' returned "
                    f"only {len(result.strip())} characters. Provide more detail."
                ),
            )

        if previous_result is not None and result.strip() == previous_result.strip():
            return ValidationResult(
                passed=False,
                reason="result identical to previous attempt — no new information",
                quality_hint=(
                    f"Step '{step_description}' returned the same output as the "
                    f"previous attempt. Try a different approach."
                ),
            )

        return ValidationResult(passed=True)
```

### 6.4 Integration in `executor.py`

After each step result is stored and before advancing to the next step,
call the validator. On failure, inject the quality hint into the step's
description and retry once (consume one additional `StepBudget` unit):

```python
# In ExecutorAgent, after step result is received:
from weebot.application.services.step_result_validator import StepResultValidator

_validator = StepResultValidator()  # stateless — instantiate once in __init__

# After result is obtained, before emitting StepEvent(COMPLETED):
validation = _validator.validate(
    result=str(result.output or ""),
    step_description=step.description,
    previous_result=getattr(step, "_last_result", None),
)
if not validation.passed and not step._retried:
    logger.info(
        "Step '%s' failed quality check (%s) — retrying with hint",
        step.id, validation.reason,
    )
    # Store hint on step for retry prompt injection
    step = step.model_copy(update={
        "description": f"{step.description}\n[Quality hint: {validation.quality_hint}]",
        "_retried": True,
    })
    # Re-queue current step (do not advance plan)
    # ... existing re-queue mechanism or set StepStatus back to PENDING
```

Implementation note: the exact re-queue mechanism depends on how
`ExecutingState` iterates steps. Read `executing.py` before implementing
to use the existing iteration pattern rather than inventing a new one.
Add `_retried: bool = False` to the `Step` domain model (domain layer —
a pure flag, no infrastructure dependency) to prevent infinite retry loops.

### 6.5 Tests — `tests/unit/test_step_result_validator.py`

- `test_empty_result_fails` — `result=""` → `passed=False`
- `test_null_string_fails` — `result="None"` → `passed=False`
- `test_too_short_fails` — `result="ok"` → `passed=False`
- `test_identical_to_previous_fails` — same result twice → `passed=False`
- `test_good_result_passes` — `result="Step completed successfully with 42 items"` → `passed=True`
- `test_quality_hint_references_step_description` — hint contains step description substring

### 6.6 Risk: Medium

Requires adding `_retried: bool` to the `Step` domain model — a pure flag
that no existing logic reads, so backward-compatible. The executor loop
change requires careful reading of `executing.py` to avoid breaking step
sequencing. Gate: `tests/unit/test_parallel_tool_execution.py` (from
tool_enhancements_plan Phase 2) must stay green.

---

## 7. Phase 4 — Cross-Lab Model Diversity

### 7.1 Goal

`PlanCriticService` and `PlannerAgent` both default to whatever single model
is passed as `context._llm`. If that model is from the same lab as the executor
model, plan critiques share training biases. Add a `RoleModelSelector` that
assigns different model IDs to different functional roles, reading from an
extended `MODEL_CASCADE` config.

### 7.2 New Files

| File | Purpose |
|------|---------|
| `weebot/application/services/role_model_selector.py` | Selects model by role |
| `tests/unit/test_role_model_selector.py` | Unit tests |

### 7.3 Extend `model_cascade_config.py`

Add a `ROLE_MODEL_CONFIG` dict mapping role names to ordered model lists:

```python
# weebot/core/model_cascade_config.py (additions only)

AGENT_ROLES = frozenset({
    "planner",    # generates initial plans
    "critic",     # validates plans (PlanCriticService, MetaCritic)
    "executor",   # executes steps (ExecutorAgent)
    "verifier",   # CoVe verification (VerifyingState)
    "summarizer", # SummarizingState
})

# Maps role → ordered list of model IDs to try (first = primary, rest = fallback)
# Design rule: "planner" and "critic" should use models from different labs
# to prevent echo-chamber plan validation.
ROLE_MODEL_CONFIG: dict[str, list[str]] = {
    "planner":    ["moonshotai/kimi-k2.6", "deepseek/deepseek-v4-flash"],
    "critic":     ["deepseek/deepseek-v4-flash", "x-ai/grok-build-0.1"],
    "executor":   ["moonshotai/kimi-k2.6", "deepseek/deepseek-v4-flash"],
    "verifier":   ["deepseek/deepseek-v4-flash", "moonshotai/kimi-k2.6"],
    "summarizer": ["moonshotai/kimi-k2.6", "deepseek/deepseek-v4-flash"],
}
```

### 7.4 `RoleModelSelector` — `weebot/application/services/role_model_selector.py`

```python
"""RoleModelSelector — assigns model IDs to functional agent roles.

Reads from ROLE_MODEL_CONFIG in model_cascade_config.  Falls back to the
flow's default model if the role is not configured or all role models are
unavailable (circuit open).

This is a pure application-layer service: no LLM calls, no I/O.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RoleModelSelector:
    """Returns the preferred model ID for a given agent role.

    Args:
        default_model: Fallback model ID when role config is absent.
    """

    def __init__(self, default_model: Optional[str] = None) -> None:
        self._default = default_model

    def select(self, role: str) -> str:
        """Return the primary model ID for *role*.

        Falls back to *default_model* if the role is not in ROLE_MODEL_CONFIG.
        """
        from weebot.core.model_cascade_config import ROLE_MODEL_CONFIG
        models = ROLE_MODEL_CONFIG.get(role, [])
        if models:
            return models[0]
        if self._default:
            return self._default
        raise ValueError(f"No model configured for role '{role}' and no default set")

    def fallback_chain(self, role: str) -> list[str]:
        """Return the full ordered fallback list for *role*."""
        from weebot.core.model_cascade_config import ROLE_MODEL_CONFIG
        return list(ROLE_MODEL_CONFIG.get(role, [self._default] if self._default else []))
```

### 7.5 Wire into `PlanCriticService`

Add an optional `model: Optional[str]` parameter to `PlanCriticService.critique()`
and pass `RoleModelSelector.select("critic")` at the call site in `CritiquingState`
and `UpdatingState`. The LLM call already accepts a `model=` kwarg via `LLMPort`.

### 7.6 Tests — `tests/unit/test_role_model_selector.py`

- `test_returns_primary_model_for_configured_role` — "critic" returns first model in config
- `test_falls_back_to_default_for_unknown_role` — unregistered role returns `default_model`
- `test_raises_without_default_for_unknown_role` — no default + unknown role raises `ValueError`
- `test_fallback_chain_returns_all_models` — chain has ≥ 2 entries for "planner"

### 7.7 Risk: Low

`ROLE_MODEL_CONFIG` is purely additive config. `RoleModelSelector` is a
stateless pure service. Call sites pass `model=` to existing LLM port methods
that already accept it. No schema changes.

---

## 8. Phase 5 — Declarative Task Complexity Presets

### 8.1 Goal

A `TaskPreset` declares which optional flow states to enable (pre-mortem,
verbose critique, strict verification), which model roles to use, and how
many steps to budget. The pre-router (Phase 6) selects the preset from task
complexity; the flow reads it at initialization.

### 8.2 New Files

| File | Purpose |
|------|---------|
| `weebot/domain/models/task_preset.py` | `TaskPreset` domain model (pure, no imports) |
| `weebot/config/task_preset_registry.py` | Built-in preset definitions |
| `tests/unit/test_task_preset.py` | Unit tests |

### 8.3 `TaskPreset` — `weebot/domain/models/task_preset.py`

```python
"""TaskPreset — declarative cost/quality configuration for a task run.

Pure domain model: no imports from Application or Infrastructure.
Presets are selected by the pre-router based on task complexity and
injected into PlanActFlowConfig at flow construction time.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskPreset:
    """Immutable configuration for a single task execution tier.

    Fields:
        name:               Human-readable identifier ("simple", "standard", "complex").
        enable_premortem:   Whether to run PremortmState before execution.
        enable_step_validation: Whether to run StepResultValidator in the executor.
        critique_warn_threshold: Override for CritiquingState.WARN_THRESHOLD (default 0.8).
        critique_revise_threshold: Override for CritiquingState.REVISE_THRESHOLD (default 0.5).
        max_steps:          Step budget override (None = use flow default).
        role_model_overrides: dict[role → model_id] — overrides ROLE_MODEL_CONFIG entries.
        notes:              Human-readable rationale (not used at runtime).
    """
    name: str
    enable_premortem: bool = False
    enable_step_validation: bool = True
    critique_warn_threshold: float = 0.8
    critique_revise_threshold: float = 0.5
    max_steps: int | None = None
    role_model_overrides: dict[str, str] = field(default_factory=dict)
    notes: str = ""
```

### 8.4 Built-in Presets — `weebot/config/task_preset_registry.py`

```python
"""Built-in task preset registry.

Three tiers mirroring Reasoner's Budget / Balanced / Premium pattern.
Presets are pure data — no LLM calls or I/O at import time.
"""
from __future__ import annotations

from weebot.domain.models.task_preset import TaskPreset

PRESET_SIMPLE = TaskPreset(
    name="simple",
    enable_premortem=False,
    enable_step_validation=False,
    critique_warn_threshold=0.6,   # Less strict — simple tasks rarely fail
    critique_revise_threshold=0.3,
    max_steps=10,
    notes="Greetings, factual lookups, single-tool tasks. Minimal overhead.",
)

PRESET_STANDARD = TaskPreset(
    name="standard",
    enable_premortem=False,
    enable_step_validation=True,
    critique_warn_threshold=0.8,
    critique_revise_threshold=0.5,
    max_steps=None,  # flow default
    notes="Multi-step tasks with moderate risk. Default tier.",
)

PRESET_COMPLEX = TaskPreset(
    name="complex",
    enable_premortem=True,
    enable_step_validation=True,
    critique_warn_threshold=0.85,  # Stricter — high-stakes tasks
    critique_revise_threshold=0.6,
    max_steps=None,
    notes="Architectural changes, long pipelines, high-risk operations.",
)

_REGISTRY: dict[str, TaskPreset] = {
    p.name: p for p in (PRESET_SIMPLE, PRESET_STANDARD, PRESET_COMPLEX)
}


def get_preset(name: str) -> TaskPreset:
    """Return a preset by name, falling back to PRESET_STANDARD."""
    return _REGISTRY.get(name, PRESET_STANDARD)


def register_preset(preset: TaskPreset) -> None:
    """Register a custom preset (useful for tests and extensions)."""
    _REGISTRY[preset.name] = preset
```

### 8.5 `PlanActFlowConfig` Changes

Add one optional field:

```python
# weebot/application/models/plan_act_flow_config.py
from weebot.domain.models.task_preset import TaskPreset

@dataclass
class PlanActFlowConfig:
    # ... existing fields ...
    task_preset: TaskPreset | None = None
    """Optional task preset controlling quality gates and model selection.
    If None, flow uses its hardcoded defaults (backward-compatible)."""
```

### 8.6 `PlanActFlow` reads preset

In `plan_act_flow.py.__init__`, after reading `cfg`:

```python
self._task_preset = cfg.task_preset  # None = legacy behavior

# Apply preset thresholds to CritiquingState if provided
if self._task_preset is not None:
    from weebot.application.flows.states.critiquing import ConfidentThresholds
    # Override class-level thresholds for this flow instance via constructor arg
    # (CritiquingState accepts optional threshold overrides — see §8.7)
```

### 8.7 `CritiquingState` threshold injection

Change `CritiquingState.__init__` to accept optional threshold overrides:

```python
class CritiquingState(FlowState):
    def __init__(
        self,
        critic: PlanCriticService | None = None,
        warn_threshold: float = ConfidentThresholds.WARN_THRESHOLD,
        revise_threshold: float = ConfidentThresholds.REVISE_THRESHOLD,
    ) -> None:
        self._critic = critic
        self._warn_threshold = warn_threshold
        self._revise_threshold = revise_threshold
```

Replace `ConfidentThresholds.WARN_THRESHOLD` with `self._warn_threshold`
in the routing logic. Existing call sites pass no thresholds → unchanged behavior.

### 8.8 Tests — `tests/unit/test_task_preset.py`

- `test_preset_is_frozen` — modifying a field raises `FrozenInstanceError`
- `test_get_preset_known_name` — `get_preset("complex")` returns `PRESET_COMPLEX`
- `test_get_preset_unknown_falls_back_to_standard` — unknown name returns `PRESET_STANDARD`
- `test_critiquing_state_respects_warn_threshold_override` — custom threshold routes correctly
- `test_premortem_enabled_by_complex_preset` — preset flag propagates to state selection

### 8.9 Risk: Low

`TaskPreset` is a frozen dataclass — no mutation, no infrastructure dependency.
`PlanActFlowConfig` change is additive (`None` default). `CritiquingState`
threshold injection is backward-compatible (existing call sites omit args).

---

## 9. Phase 6 — Parallel Multi-Agent Pre-Router

### 9.1 Goal

Replace `KeywordTaskRouter` (substring matching, crude confidence) with a
`AgentPreRouter` that launches 4 parallel LLM sub-agents to classify every
incoming task. Add regex fast-paths that bypass the full Plan-Act loop
entirely for simple tasks.

### 9.2 New Files

| File | Purpose |
|------|---------|
| `weebot/application/services/pre_router/` | Sub-package |
| `weebot/application/services/pre_router/__init__.py` | Public API |
| `weebot/application/services/pre_router/agent_pre_router.py` | Orchestrator |
| `weebot/application/services/pre_router/complexity_agent.py` | Sub-agent 1 |
| `weebot/application/services/pre_router/direct_answer_agent.py` | Sub-agent 2 |
| `weebot/application/services/pre_router/tool_hint_agent.py` | Sub-agent 3 |
| `weebot/application/services/pre_router/web_search_agent.py` | Sub-agent 4 |
| `weebot/application/services/pre_router/fast_paths.py` | Regex fast-paths |
| `weebot/application/services/pre_router/routing_decision.py` | Result dataclass |
| `tests/unit/test_agent_pre_router.py` | Unit tests |

### 9.3 `RoutingDecision` — `routing_decision.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from weebot.domain.models.task_route import TaskComplexity

@dataclass(frozen=True)
class RoutingDecision:
    complexity: TaskComplexity          # simple / medium / complex
    is_direct_answer: bool              # skip Plan-Act, answer inline
    needs_web_search: bool              # route to search tool first
    suggested_tools: list[str]          # hint for executor tool selection
    preset_name: str                    # maps to TaskPreset (Phase 5)
    confidence: float                   # 0.0–1.0
    fast_path: bool = False             # came from regex, no LLM used
    reason: str = ""                    # debug info
```

### 9.4 Sub-Agent Base Pattern

Each sub-agent follows the same contract:

```python
# Each sub-agent in pre_router/
class _BaseRouterSubAgent:
    TIMEOUT_SECONDS: float = 6.0

    async def classify(self, query: str) -> dict:
        """Return a small dict with the agent's classification result.
        Never raises — exceptions return a default/fallback dict."""
        ...
```

Sub-agent outputs are merged heuristically (no 5th LLM call — same pattern
as Reasoner's HyperGate):

| Sub-agent | Output key | Values |
|-----------|-----------|--------|
| `ComplexityAgent` | `complexity` | `"simple"` / `"medium"` / `"complex"` |
| `DirectAnswerAgent` | `is_direct` | `True` / `False` |
| `ToolHintAgent` | `tools` | `["bash", "web_search", ...]` |
| `WebSearchAgent` | `needs_web_search` | `True` / `False` |

### 9.5 Fast-Path Patterns — `fast_paths.py`

```python
"""Regex fast-paths — classify obvious queries without any LLM call."""
import re

_GREETING = re.compile(
    r"^\s*(hi|hello|hey|good\s*(morning|afternoon|evening)|thanks?|thank\s+you)\b",
    re.IGNORECASE,
)
_SIMPLE_FACTUAL = re.compile(
    r"^\s*(what\s+is|who\s+is|when\s+did|where\s+is|how\s+many)\b.{0,80}\??\s*$",
    re.IGNORECASE,
)
_REALTIME = re.compile(
    r"\b(current\s+price|live\s+score|today'?s?\s+weather|stock\s+price|news\s+today)\b",
    re.IGNORECASE,
)

def fast_path_check(query: str) -> dict | None:
    """Return a routing hint if the query matches a fast-path pattern.

    Returns None if no fast-path matches (fall through to sub-agents).
    """
    if _GREETING.match(query):
        return {"is_direct": True, "complexity": "simple", "fast_path": True}
    if _SIMPLE_FACTUAL.match(query):
        return {"is_direct": True, "complexity": "simple", "fast_path": True}
    if _REALTIME.search(query):
        return {"needs_web_search": True, "complexity": "medium", "fast_path": True}
    return None
```

### 9.6 `AgentPreRouter.route()` Orchestration

```python
async def route(self, query: str) -> RoutingDecision:
    # 1. Fast-path check (no LLM)
    fast = fast_path_check(query)
    if fast:
        return self._build_decision(query, fast)

    # 2. Launch all 4 sub-agents in parallel
    results = await asyncio.gather(
        self._complexity.classify(query),
        self._direct_answer.classify(query),
        self._tool_hint.classify(query),
        self._web_search.classify(query),
        return_exceptions=True,
    )

    # 3. Merge (replace exceptions with defaults)
    merged = self._merge(results)

    # 4. Build decision (no 5th LLM call)
    return self._build_decision(query, merged)
```

### 9.7 Adapter Registration

`AgentPreRouter` implements `TaskRouterPort` (existing port). Register as the
primary implementation in `weebot/application/di/_factories.py`:

```python
@staticmethod
def _create_task_router(llm: LLMPort) -> TaskRouterPort:
    import os
    if os.getenv("WEEBOT_ROUTER", "agent").lower() == "keyword":
        # Escape hatch: allow keyword router for environments without LLM access
        from weebot.application.services.keyword_task_router import KeywordTaskRouter
        return KeywordTaskRouter()
    from weebot.application.services.pre_router.agent_pre_router import AgentPreRouter
    return AgentPreRouter(llm=llm)
```

`KeywordTaskRouter` is kept as a fallback — not deleted.

### 9.8 Tests — `tests/unit/test_agent_pre_router.py`

- `test_fast_path_greeting_no_llm_call` — mock LLM not called; `is_direct_answer=True`
- `test_fast_path_realtime_sets_web_search` — `needs_web_search=True`
- `test_parallel_agents_all_called` — 4 sub-agents each called once; gather fires
- `test_one_agent_failure_does_not_abort` — sub-agent 2 raises; other 3 still merge
- `test_complex_task_returns_complex_preset` — complex classification → `preset_name="complex"`
- `test_simple_task_returns_simple_preset` — simple classification → `preset_name="simple"`
- `test_env_fallback_to_keyword_router` — `WEEBOT_ROUTER=keyword` returns `KeywordTaskRouter`

### 9.9 Risk: Medium

This is the largest change. `KeywordTaskRouter` is kept as a fallback via env
var. All 4 sub-agents have hard 6s timeouts and return defaults on failure —
the router can never block indefinitely. The `TaskRouterPort` interface is
unchanged, so all call sites work with zero modification.

---

## 10. Phase 7 — Tree-of-Thoughts Plan Revision

### 10.1 Goal

`UpdatingState` currently calls the planner once (via CQRS mediator) and
accepts the result. Replace this with a ToT-flavored multi-candidate approach:
generate 3 candidate revision strategies, score each against the failure
context, and proceed with the highest-scoring candidate.

### 10.2 New Files

| File | Purpose |
|------|---------|
| `weebot/application/services/plan_revision_scorer.py` | Score candidate revisions |
| `tests/unit/test_plan_revision_scorer.py` | Unit tests |

### 10.3 `PlanRevisionScorer` — `plan_revision_scorer.py`

```python
"""PlanRevisionScorer — scores candidate plan revisions for ToT selection.

Given N candidate revised plans and the failure context that triggered
the revision, uses a single cheap LLM call to score each candidate 0–10
and return the index of the best one.

On timeout or parse failure, returns index 0 (first candidate) — the
caller always gets a valid selection.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort
    from weebot.domain.models.plan import Plan

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a plan evaluator. Given a failed step context and
N candidate revised plans, score each plan 0-10 on:
- Does it avoid repeating the approach that just failed?
- Are the steps concrete and achievable?
- Is the overall strategy sound?

Return ONLY valid JSON: {"scores": [score_for_plan_0, score_for_plan_1, ...]}"""

_TIMEOUT_SECONDS = 10.0


class PlanRevisionScorer:
    """Scores N candidate plan revisions and returns the index of the best."""

    def __init__(self, llm: "LLMPort") -> None:
        self._llm = llm

    async def select_best(
        self,
        candidates: list["Plan"],
        failure_context: str,
    ) -> int:
        """Return the index of the highest-scoring candidate plan.

        Falls back to index 0 on any error.
        """
        if len(candidates) <= 1:
            return 0
        try:
            import asyncio
            plans_text = "\n\n".join(
                f"Plan {i}:\n" + "\n".join(f"  {s.description}" for s in p.steps)
                for i, p in enumerate(candidates)
            )
            user_msg = (
                f"Failure context: {failure_context[:300]}\n\n"
                f"Candidate revised plans:\n{plans_text}"
            )
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.0,
                    max_tokens=100,
                ),
                timeout=_TIMEOUT_SECONDS,
            )
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            scores: list[float] = json.loads(raw).get("scores", [])
            if scores and len(scores) == len(candidates):
                return int(scores.index(max(scores)))
        except Exception as exc:
            logger.debug("PlanRevisionScorer fallback to index 0: %s", exc)
        return 0
```

### 10.4 Integration in `UpdatingState`

Wrap the mediator call in a 3-candidate loop. The mediator already accepts a
`reason` string — vary the reason slightly for each candidate to guide
diversity:

```python
_REVISION_STRATEGIES = [
    "Try a completely different approach that avoids the failed strategy.",
    "Break the failing step into smaller, more targeted sub-steps.",
    "Use a different tool or method than was used in the failed attempt.",
]

# After determining failure context, generate 3 candidates:
candidates: list[Plan] = []
for strategy_hint in _REVISION_STRATEGIES:
    cmd_result = await context._mediator.send(
        UpdatePlanCommand(
            session_id=context._session.id,
            updates={"last_step_id": last_step.id, "failure_context": fc},
            reason=f"{base_reason} Strategy: {strategy_hint}",
            model=context._model or MODEL_BUDGET,
        )
    )
    if cmd_result.success and cmd_result.data.get("plan"):
        candidates.append(Plan.model_validate(cmd_result.data["plan"]))

if not candidates:
    # Fallback: single-shot as before
    ...
elif len(candidates) == 1:
    context._plan = candidates[0]
else:
    scorer = PlanRevisionScorer(llm=context._llm)
    fc_text = str(last_step.result or "")
    best_idx = await scorer.select_best(candidates, fc_text)
    context._plan = candidates[best_idx]
    logger.info("ToT selected candidate %d of %d", best_idx, len(candidates))
```

### 10.5 Tests — `tests/unit/test_plan_revision_scorer.py`

- `test_selects_highest_score` — 3 plans, scores [3, 8, 5]; returns index 1
- `test_single_candidate_returns_zero` — 1 plan; no LLM call, returns 0
- `test_timeout_returns_zero` — mock LLM raises `asyncio.TimeoutError`; returns 0
- `test_parse_failure_returns_zero` — mock returns malformed JSON; returns 0
- `test_scores_length_mismatch_returns_zero` — 3 plans but 2 scores; returns 0

### 10.6 Risk: High

Tripling the number of CQRS mediator calls in `UpdatingState` increases latency
and cost for every plan update cycle. Mitigate with a feature flag:

```python
# In PlanActFlowConfig:
enable_tot_revision: bool = False  # Default off until validated in production
```

Only enable when `task_preset.name == "complex"` (Phase 5), keeping standard
and simple tasks on the current single-shot path.

---

## 11. Phase 8 — Hot/Warm/Cold Memory Lifecycle

### 11.1 Goal

`PersistentMemoryTool` writes to `~/.weebot/memory/AGENT.md` and
`~/.weebot/memory/USER.md` with no size management. Add a
`MemoryLifecycleService` that periodically compresses old entries (entries
older than 30 days) into a summary, keeping the active files small and
LLM-prompt-friendly.

### 11.2 New Files

| File | Purpose |
|------|---------|
| `weebot/application/services/memory_lifecycle.py` | Archival + compression service |
| `tests/unit/test_memory_lifecycle.py` | Unit tests |

### 11.3 `MemoryLifecycleService` — `memory_lifecycle.py`

```python
"""MemoryLifecycleService — tiered archival for persistent memory files.

Hot  (age ≤ HOT_DAYS):  entries kept verbatim in the active file.
Warm (HOT_DAYS < age ≤ ARCHIVE_DAYS):  entries moved to AGENT_archive.md.
Cold (age > ARCHIVE_DAYS):  entries summarised into AGENT_summary.md and
    removed from the archive.

The active file is the LLM-injected snapshot; archive and summary are
stored on disk but not injected at session start.

Timestamps: entries in AGENT.md and USER.md use the § delimiter.
A timestamp comment is appended on write: [written: YYYY-MM-DD].
This service reads that comment to determine age.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)

HOT_DAYS = 7
ARCHIVE_DAYS = 30
DELIMITER = "§"
_TIMESTAMP_RE = re.compile(r"\[written:\s*(\d{4}-\d{2}-\d{2})\]")


class MemoryLifecycleService:
    """Manages hot/warm/cold tiering for persistent memory files.

    Args:
        memory_dir: Path to ~/.weebot/memory/ (or equivalent).
        llm: Optional LLM for cold-tier summarisation.
             If None, cold entries are deleted without summarisation.
    """

    def __init__(self, memory_dir: Path, llm: "LLMPort | None" = None) -> None:
        self._dir = memory_dir
        self._llm = llm

    async def run_lifecycle(self, file_stem: str = "AGENT") -> None:
        """Run the hot/warm/cold pass on *file_stem*.md.

        Safe to call repeatedly — idempotent for entries without a timestamp.
        """
        active_path = self._dir / f"{file_stem}.md"
        archive_path = self._dir / f"{file_stem}_archive.md"
        summary_path = self._dir / f"{file_stem}_summary.md"

        if not active_path.exists():
            return

        today = date.today()
        raw = active_path.read_text(encoding="utf-8")
        entries = [e.strip() for e in raw.split(DELIMITER) if e.strip()]

        hot: list[str] = []
        warm: list[str] = []
        cold: list[str] = []

        for entry in entries:
            age_days = self._entry_age_days(entry, today)
            if age_days is None or age_days <= HOT_DAYS:
                hot.append(entry)
            elif age_days <= ARCHIVE_DAYS:
                warm.append(entry)
            else:
                cold.append(entry)

        # Rewrite active file with only hot entries
        active_path.write_text(
            f"{DELIMITER}\n".join(hot) + (f"\n{DELIMITER}\n" if hot else ""),
            encoding="utf-8",
        )

        # Append warm entries to archive
        if warm:
            with archive_path.open("a", encoding="utf-8") as f:
                f.write(f"{DELIMITER}\n".join(warm) + f"\n{DELIMITER}\n")

        # Summarise and discard cold entries
        if cold and self._llm is not None:
            summary = await self._summarise(cold)
            with summary_path.open("a", encoding="utf-8") as f:
                f.write(f"\n## Summary ({today.isoformat()})\n{summary}\n")
        elif cold:
            logger.debug(
                "Discarded %d cold entries (no LLM for summarisation)", len(cold)
            )

        logger.info(
            "Memory lifecycle: %d hot, %d warm→archive, %d cold",
            len(hot), len(warm), len(cold),
        )

    @staticmethod
    def _entry_age_days(entry: str, today: date) -> int | None:
        m = _TIMESTAMP_RE.search(entry)
        if not m:
            return None
        try:
            written = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            return (today - written).days
        except ValueError:
            return None

    async def _summarise(self, entries: list[str]) -> str:
        try:
            import asyncio
            text = "\n---\n".join(entries[:20])
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[{
                        "role": "user",
                        "content": (
                            f"Summarise these agent memory entries into 3–5 bullet points "
                            f"preserving only durable facts and preferences:\n\n{text}"
                        ),
                    }],
                    temperature=0.0,
                    max_tokens=300,
                ),
                timeout=15.0,
            )
            return (response.content or "").strip()
        except Exception as exc:
            logger.debug("Memory summarisation failed: %s", exc)
            return "(summarisation failed — entries discarded)"
```

### 11.4 Timestamp Injection in `PersistentMemoryTool`

When the tool appends an entry via the `add` action, append a timestamp comment:

```python
# In PersistentMemoryTool.execute(), "add" action:
from datetime import date
entry_with_ts = f"{content.strip()} [written: {date.today().isoformat()}]"
```

Existing entries without a timestamp are treated as `age=None` → stay hot.
Backward-compatible.

### 11.5 DI / Scheduler Integration

The lifecycle service should run at session end (Stop hook) or as a weekly
scheduled job via the existing `SkillCurator` APScheduler pattern:

```python
# In weebot/application/di/__init__.py
from weebot.application.services.memory_lifecycle import MemoryLifecycleService
from pathlib import Path

lifecycle = MemoryLifecycleService(
    memory_dir=Path.home() / ".weebot" / "memory",
    llm=container.get(LLMPort),
)
# Register as a weekly job alongside SkillCurator
scheduler.add_job(
    lambda: asyncio.run(lifecycle.run_lifecycle("AGENT")),
    "interval", days=7, id="memory_lifecycle_agent",
)
```

### 11.6 Tests — `tests/unit/test_memory_lifecycle.py`

- `test_hot_entries_stay_in_active_file` — entry written 3 days ago; remains in AGENT.md
- `test_warm_entries_moved_to_archive` — entry 15 days old; removed from active, present in archive
- `test_cold_entries_removed_from_active` — entry 45 days old; removed from active
- `test_entry_without_timestamp_stays_hot` — entry with no `[written:]` tag kept in active
- `test_summarise_called_for_cold_entries` — mock LLM called once for cold batch
- `test_no_llm_cold_entries_discarded` — `llm=None`; cold entries simply removed, no error

### 11.7 Risk: Low

Purely additive file management. Active file writes are idempotent. The
lifecycle service never modifies in-flight session data — it only touches
disk files when explicitly called. Existing `PersistentMemoryTool` behaviour
is unchanged for the `read` action (reads active file only).

---

## 12. Test Strategy Summary

Each phase ships with its own test file. Shared fixtures for mock LLM and
mock `PlanActFlow` context live in `tests/unit/conftest.py`.

| Phase | New test file | Min coverage target |
|-------|---------------|---------------------|
| 1 | `test_premortem_state.py` | 95% of `PremortmAnalyzer` + `PremortmState` |
| 2 | `test_updating_state_critic.py` | 90% of new critic-call path |
| 3 | `test_step_result_validator.py` | 100% of `StepResultValidator.validate()` |
| 4 | `test_role_model_selector.py` | 100% of `RoleModelSelector` |
| 5 | `test_task_preset.py` | 100% of preset registry + threshold propagation |
| 6 | `test_agent_pre_router.py` | 90% of `AgentPreRouter.route()` |
| 7 | `test_plan_revision_scorer.py` | 100% of `PlanRevisionScorer.select_best()` |
| 8 | `test_memory_lifecycle.py` | 95% of `MemoryLifecycleService` |

Run after every phase:

```bash
pytest tests/unit/test_architecture_fitness.py -v   # must stay green
pytest tests/unit/ -v --cov=weebot --cov-report=term-missing
```

---

## 13. Implementation Order & Dependencies

```
Week 1:  Phase 1 (pre-mortem)    — additive new state, zero risk
         Phase 2 (updating hints) — one-line reuse, zero risk
         Phase 4 (role models)    — config extension, zero risk

Week 2:  Phase 3 (step validation) — new service + executor change
         Phase 5 (presets)         — new domain model, depends on Phase 4

Week 3:  Phase 6 (pre-router)     — biggest surface, depends on Phase 5
         Phase 8 (memory lifecycle) — independent, low risk

Week 4:  Phase 7 (ToT revision)   — highest complexity, feature-flagged off
                                     until Phases 1–6 stable
```

Each phase merges to `feature/reasoner-enhancements` via a separate PR.
Phase 7 is gated behind `enable_tot_revision=False` in `PlanActFlowConfig`
and only activated for `complex` task presets.

---

## 14. Invariants to Preserve

The following must not change behaviour regardless of which phases are active:

1. **`CritiquingState` low-confidence path** — must still return to `PlanningState`
   when confidence < revise_threshold; pre-mortem must never run on a rejected plan
2. **`VerifyingState` feature toggle** — `WEEBOT_COVE_ENABLED=false` must still skip
   verification; no new env var dependency introduced on that path
3. **`PlanStuckError` termination** — `PlanHistory.is_too_similar()` still fires;
   ToT candidates that are all similar to history must still trigger the error
4. **`ToolResult.is_error` semantics** — step validation rejects quality-suspect
   non-error results but never converts them to errors; `is_error` stays `False`
5. **Architecture fitness** — all existing `tests/unit/test_architecture_fitness.py`
   tests pass after every phase
6. **`KeywordTaskRouter` preserved** — not deleted; accessible via `WEEBOT_ROUTER=keyword`
7. **`PlanActFlowConfig` backward compatibility** — all new fields default to `None`
   or `False`; existing construction call sites require zero changes
