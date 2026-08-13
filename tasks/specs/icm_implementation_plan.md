# ICM-Derived Improvements — Implementation Plan

**Source**: `tasks/specs/icm_weebot_analysis.md` (gap analysis)
**Target model**: Claude Sonnet 5
**Date**: 2026-08-13

---

## Overview

Three changes, ordered by dependency chain:

1. **Phase A**: Per-step context scoping (P0) — Step model + prompt builder + planner prompt
2. **Phase B**: Reference/Working prompt separation (P2) — prompt builder restructuring
3. **Phase C**: Recurring correction tracker (P1) — new service + wire to skill promotion

Phase A is the largest. Phase B is a pure prompt-engineering refactor inside the prompt builder (low risk, do after A since A changes the same function). Phase C is a new service with its own tests, independent of A/B — can run in parallel if desired but logically follows because it benefits from scoped context metadata.

---

## Phase A: Per-Step Context Scoping

### Goal

Each plan step declares what context sources it needs. The prompt builder assembles only those sources. Steps that run shell commands skip personality/user-profile injection. Steps that write creative content get the full stack.

### A1. Add `ContextScope` enum and `context_scope` field to Step

**File**: `weebot/domain/models/plan.py`

Add after `StepStatus` enum:

```python
class ContextScope(str, Enum):
    """What context sources a step needs in its executor prompt.
    
    The planner assigns this at plan-creation time. The prompt builder
    uses it to select which sources to include, following ICM's
    principle of stage-scoped context loading.
    """
    FULL = "full"          # all sources (backward compat default)
    MINIMAL = "minimal"    # base prompt + harness only (shell commands, file ops)
    SKILL = "skill"        # base + harness + matched skills (technical steps)
    CREATIVE = "creative"  # base + harness + skills + user profile + personality
```

Add field to `Step`:

```python
class Step(BaseModel):
    # ... existing fields ...
    context_scope: ContextScope = Field(
        default=ContextScope.FULL,
        description="Which context sources the executor loads for this step. "
                    "Set by the planner. FULL = backward compat.",
    )
```

**Design pattern**: Value Object enum (immutable, domain-level). Default `FULL` ensures zero breaking changes — every existing plan works identically.

**Architecture rule**: Domain layer only. No imports from application/infrastructure.

### A2. Update `build_executor_prompt` to respect scope

**File**: `weebot/application/agents/executor/_prompt_builder.py`

Change signature to accept scope:

```python
async def build_executor_prompt(
    step_description: str,
    *,
    base_prompt: str,
    context_scope: str = "full",   # ContextScope.value
    harness_block: Optional[str] = None,
    skill_prompt: Optional[str] = None,
    skill_retriever: Optional[Any] = None,
    behavioral_learner: Optional[Any] = None,
    state_repo: Optional[Any] = None,
    personality: Optional[Any] = None,
    profile_name: str = "",
) -> str:
```

Use a set-based inclusion check:

```python
# Scoping table — which sources each scope includes
_SCOPE_SOURCES: dict[str, frozenset[str]] = {
    "full":     frozenset({"boot", "base", "harness", "skill", "skill_retriever", "behavioral", "profile", "personality"}),
    "minimal":  frozenset({"boot", "base", "harness"}),
    "skill":    frozenset({"boot", "base", "harness", "skill", "skill_retriever", "behavioral"}),
    "creative": frozenset({"boot", "base", "harness", "skill", "skill_retriever", "behavioral", "profile", "personality"}),
}
```

Each existing block becomes guarded:

```python
sources = _SCOPE_SOURCES.get(context_scope, _SCOPE_SOURCES["full"])

# Boot block
if "boot" in sources:
    parts.append(...)

# Base prompt
if "base" in sources and base_prompt:
    parts.append(base_prompt)

# Harness
if "harness" in sources and harness_block:
    parts.append(harness_block)

# Skill
if "skill" in sources and skill_prompt:
    parts.append(...)

# Skill retriever
if "skill_retriever" in sources and skill_retriever is not None:
    ...

# Behavioral rules
if "behavioral" in sources and behavioral_learner is not None:
    ...

# User profile
if "profile" in sources and state_repo is not None:
    ...

# Personality
if "personality" in sources and personality is not None and personality.loaded:
    ...
```

**Design pattern**: Strategy via lookup table. No conditionals per scope — adding a new scope = one dict entry.

### A3. Thread scope through the call chain

**File**: `weebot/application/agents/executor/_base.py` (~line 432)

Pass the current step's scope:

```python
system_prompt = await build_executor_prompt(
    step_description=step.description,
    base_prompt=base_prompt,
    context_scope=step.context_scope.value if hasattr(step, 'context_scope') else "full",
    harness_block=self._harness_instruction_block,
    # ... rest unchanged ...
)
```

Also gate the user profile cache append (~line 445):

```python
scope_val = getattr(step, 'context_scope', None)
if scope_val and scope_val.value not in ("full", "creative"):
    pass  # skip profile for minimal/skill scopes
elif getattr(self, '_user_profile_cache', ''):
    system_prompt += f"\n\n## User Profile\n{self._user_profile_cache}"
```

### A4. Update planner prompt to emit `context_scope`

**File**: `weebot/config/prompts/planner_system.txt`

Add to the JSON structure documentation (after `acceptance_criteria`):

```
    {"id": "step-1", "description": "...", "status": "pending",
     "acceptance_criteria": ["..."],
     "context_scope": "minimal|skill|creative|full"
    }
```

Add a CONTEXT SCOPE RULES section after STEP BUDGET:

```
CONTEXT SCOPE RULES (assign to each step):
- "minimal" — step runs shell commands, file ops, or mechanical tasks.
  No personality, user profile, or skill injection needed.
  Examples: "Run pytest", "Create directory", "Copy file", "Get-ChildItem"
- "skill" — step requires technical skills but not creative persona.
  Examples: "Implement function", "Write unit test", "Fix bug", "Refactor"
- "creative" — step produces user-facing content, prose, or design.
  Examples: "Write README", "Draft email", "Generate copy", "Design UI"
- "full" — default. Use when unsure or step needs everything.

Assign the most restrictive scope that covers the step's needs.
When in doubt, use "skill" for code steps and "minimal" for shell steps.
```

### A5. Tests

**File**: `tests/unit/test_prompt_builder_scope.py` (new)

Test cases:
1. `test_minimal_scope_excludes_profile_and_personality` — build with scope="minimal", assert user profile and personality text absent from result
2. `test_skill_scope_includes_skills_excludes_profile` — build with scope="skill", assert skill content present, profile absent
3. `test_creative_scope_includes_everything` — build with scope="creative", assert all sources present
4. `test_full_scope_backward_compat` — build with scope="full" (or no scope), assert identical to current behavior
5. `test_unknown_scope_falls_back_to_full` — build with scope="bogus", assert full behavior
6. `test_step_model_accepts_context_scope` — create Step with context_scope=ContextScope.MINIMAL, assert serialization/deserialization roundtrip

**File**: `tests/unit/test_architecture_fitness.py`

Add fitness test: `ContextScope` must be in `weebot.domain.models.plan` (domain layer, no application imports).

---

## Phase B: Reference/Working Prompt Separation

### Goal

Structure the assembled prompt into labeled sections so the model receives clear signals about what constrains behavior vs what to transform.

### B1. Restructure prompt output in `build_executor_prompt`

**File**: `weebot/application/agents/executor/_prompt_builder.py`

Instead of flat `parts.append(...)`, collect into two buckets:

```python
constraints: list[str] = []   # "internalize as rules" — Layer 3 equivalent
task_parts: list[str] = []    # "process as input" — Layer 4 equivalent

# Boot block → constraints (always)
constraints.append(boot_block)

# Base prompt → constraints
if base_prompt:
    constraints.append(base_prompt)

# Harness → constraints
if harness_block:
    constraints.append(harness_block)

# Skills → constraints (they're reference material)
if skill content:
    constraints.append(skill_text)

# Behavioral rules → constraints
if behavioral rules:
    constraints.append(rules_text)

# User profile → constraints (persona context)
if user profile:
    constraints.append(profile_text)

# Personality → constraints
if personality:
    constraints.append(personality_text)

# Final assembly with structural markers
sections = []
if constraints:
    sections.append("## CONSTRAINTS\nInternalize the following as rules and patterns to follow.\n\n" + "\n\n".join(constraints))
if task_parts:
    sections.append("## TASK\nProcess and transform the following input.\n\n" + "\n\n".join(task_parts))
return "\n\n---\n\n".join(sections)
```

Note: The step description itself is injected by the caller (ExecutorAgent._base.py), not by the prompt builder, so the prompt builder only handles constraint-side content. The task/working material (step description, prior step results) arrives via the conversation messages, which is already structurally separate. This means Phase B is mostly about adding the `## CONSTRAINTS` header and brief framing line — minimal change.

### B2. Tests

Add to `tests/unit/test_prompt_builder_scope.py`:

1. `test_constraints_header_present` — assert "## CONSTRAINTS" appears in output
2. `test_constraints_section_contains_skills` — skill content appears under CONSTRAINTS header

---

## Phase C: Recurring Correction Tracker

### Goal

Track diffs between failed step outputs and their corrected re-executions. After N recurring patterns, surface them as candidates for source-level improvement (skill update, planner prompt amendment, behavioral rule).

### C1. Domain model: `CorrectionRecord`

**File**: `weebot/domain/models/correction.py` (new)

```python
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

class CorrectionRecord(BaseModel):
    """Records the delta between a failed/corrected step output and its replacement.
    
    Accumulated records surface recurring patterns — the "edit-source principle"
    from ICM §6.3: recurring output edits point to fixable source-level problems.
    """
    session_id: str
    step_id: str
    step_description: str
    original_output: str = Field(description="Output before correction/replan")
    corrected_output: str = Field(description="Output after successful re-execution")
    correction_category: str = Field(
        default="",
        description="LLM-classified category: tone, format, scope, accuracy, missing_info",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Design**: Immutable Pydantic model. Domain layer only.

### C2. Application service: `CorrectionTracker`

**File**: `weebot/application/services/correction_tracker.py` (new)

```python
class CorrectionTracker:
    """Tracks recurring output corrections and surfaces source-level fix suggestions.
    
    Implements ICM's edit-source principle: "editing output fixes this run;
    editing the source fixes every future run."
    
    Wired into the replan/retry path in ExecutingState. When a step fails and
    is re-executed (or when the plan is updated after failure), records the
    delta. After PATTERN_THRESHOLD recurring corrections of the same category,
    emits a CorrectionPatternDetected domain event.
    """
    PATTERN_THRESHOLD = 3
    
    def __init__(self, state_repo: StateRepositoryPort, llm: Optional[LLMPort] = None):
        self._state_repo = state_repo
        self._llm = llm
    
    async def record_correction(
        self,
        session_id: str,
        step: Step,
        original_output: str,
        corrected_output: str,
    ) -> Optional[CorrectionRecord]:
        """Record a correction and check for recurring patterns."""
        category = await self._classify_correction(original_output, corrected_output)
        record = CorrectionRecord(
            session_id=session_id,
            step_id=step.id,
            step_description=step.description,
            original_output=original_output[:500],
            corrected_output=corrected_output[:500],
            correction_category=category,
        )
        await self._state_repo.save_correction_record(record)
        
        count = await self._state_repo.count_corrections_by_category(category)
        if count >= self.PATTERN_THRESHOLD:
            return record  # caller emits domain event
        return None
    
    async def _classify_correction(self, original: str, corrected: str) -> str:
        """Classify the type of correction. LLM if available, heuristic fallback."""
        if self._llm:
            return await self._classify_with_llm(original, corrected)
        return self._classify_heuristic(original, corrected)
    
    @staticmethod
    def _classify_heuristic(original: str, corrected: str) -> str:
        """Keyword-based classification when no LLM available."""
        len_ratio = len(corrected) / max(len(original), 1)
        if len_ratio < 0.7:
            return "scope"        # significantly shortened
        if len_ratio > 1.5:
            return "missing_info" # significantly expanded
        return "accuracy"         # same-size rewrite
    
    async def _classify_with_llm(self, original: str, corrected: str) -> str:
        """LLM-based classification into: tone, format, scope, accuracy, missing_info."""
        # cheap call, MAX_TOKENS_TINY, TEMPERATURE_PRECISE
        ...
    
    async def get_recurring_patterns(self, min_count: int = 3) -> list[dict]:
        """Return correction categories that exceed threshold."""
        return await self._state_repo.get_correction_patterns(min_count)
```

**Design pattern**: Application Service. Depends on ports (StateRepositoryPort, LLMPort) — no infrastructure leakage. Classification uses Strategy (LLM when available, heuristic fallback) matching BehavioralLearner's existing pattern.

### C3. Domain event: `CorrectionPatternDetected`

**File**: `weebot/domain/models/event.py`

Add alongside existing `SkillDistilled` / `SkillPromoted`:

```python
class CorrectionPatternDetected(DomainEvent):
    """Recurring correction pattern detected — candidate for source-level fix.
    
    Connects to SkillPromotionGate: recurring corrections in a category
    can surface as behavioral rules or skill amendments.
    """
    type: Literal["correction_pattern_detected"] = "correction_pattern_detected"
    category: str
    count: int
    sample_step_description: str
    suggested_fix: str = ""
```

### C4. Persistence: add correction storage to StateRepositoryPort

**File**: `weebot/application/ports/state_repo_port.py`

Add abstract methods:

```python
async def save_correction_record(self, record: "CorrectionRecord") -> None: ...
async def count_corrections_by_category(self, category: str) -> int: ...
async def get_correction_patterns(self, min_count: int = 3) -> list[dict]: ...
```

**File**: `weebot/infrastructure/persistence/sqlite_state_repo.py`

Implement with a `correction_records` table:

```sql
CREATE TABLE IF NOT EXISTS correction_records (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    step_description TEXT,
    original_output TEXT,
    corrected_output TEXT,
    correction_category TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correction_category ON correction_records(correction_category);
```

Use existing `_ensure_table` pattern from the repo.

### C5. Wire into ExecutingState replan/retry path

**File**: `weebot/application/flows/states/executing.py`

When a step transitions from FAILED/UNVERIFIED to re-execution, capture the delta:

```python
# In the retry/replan branch, after the step has been re-executed successfully:
if previous_result and step.result and correction_tracker:
    pattern = await correction_tracker.record_correction(
        session_id=context._session.id,
        step=step,
        original_output=previous_result,
        corrected_output=step.result,
    )
    if pattern:
        from weebot.domain.models.event import CorrectionPatternDetected
        yield CorrectionPatternDetected(
            category=pattern.correction_category,
            count=correction_tracker.PATTERN_THRESHOLD,
            sample_step_description=step.description,
        )
```

### C6. Wire CorrectionPatternDetected to BehavioralLearner

**File**: `weebot/application/flows/plan_act_flow.py` (or event handler)

When `CorrectionPatternDetected` fires, auto-create a behavioral rule:

```python
# In the event handling path:
if isinstance(event, CorrectionPatternDetected):
    rule_text = f"Recurring {event.category} corrections detected. {event.suggested_fix or 'Review source prompts for this pattern.'}"
    await behavioral_learner.learn_from_correction(
        user_message=rule_text,
        context={"step_description": event.sample_step_description, "tool_name": ""},
    )
```

This closes the loop: recurring output edits → behavioral rule → injected into future prompts → fewer corrections needed.

### C7. Tests

**File**: `tests/unit/test_correction_tracker.py` (new)

1. `test_record_correction_below_threshold` — record 2 corrections, assert no pattern returned
2. `test_record_correction_at_threshold` — record 3 corrections same category, assert pattern returned
3. `test_heuristic_classification_scope` — 70% shorter output classified as "scope"
4. `test_heuristic_classification_missing_info` — 150% longer output classified as "missing_info"
5. `test_heuristic_classification_accuracy` — same-length output classified as "accuracy"

**File**: `tests/unit/test_architecture_fitness.py`

Add fitness test: `CorrectionRecord` must be in `weebot.domain.models` (domain layer).

---

## Execution Order

```
Phase A (per-step context scoping):
  A1 → A5 (domain model + tests first — TDD)
  A2 → A3 (prompt builder + call chain)
  A4 (planner prompt — last, since it's just text)

Phase B (prompt separation):
  B1 → B2 (refactor prompt builder + tests)
  Must follow A2 since both touch _prompt_builder.py

Phase C (correction tracker):
  C1 → C7 (domain model + tests first)
  C2 (service)
  C3 → C4 (event + persistence)
  C5 → C6 (wiring)
  Can run independently of A/B
```

## Validation Checklist

After all phases:

- [ ] `pytest tests/unit/test_architecture_fitness.py -v` — all pass (new fitness tests included)
- [ ] `pytest tests/unit/test_prompt_builder_scope.py -v` — all pass
- [ ] `pytest tests/unit/test_correction_tracker.py -v` — all pass
- [ ] `pytest tests/ -v` — no regressions (existing tests unchanged)
- [ ] Manual smoke: create a plan with trivial steps, verify minimal scope produces shorter prompt
- [ ] Manual smoke: simulate 3 same-category corrections, verify behavioral rule created

## Files Changed (Summary)

| File | Change Type | Phase |
|------|-------------|-------|
| `weebot/domain/models/plan.py` | Edit (add ContextScope, Step.context_scope) | A |
| `weebot/application/agents/executor/_prompt_builder.py` | Edit (scope guard + CONSTRAINTS structure) | A, B |
| `weebot/application/agents/executor/_base.py` | Edit (pass scope, gate profile) | A |
| `weebot/config/prompts/planner_system.txt` | Edit (add scope docs to planner) | A |
| `weebot/domain/models/correction.py` | New | C |
| `weebot/application/services/correction_tracker.py` | New | C |
| `weebot/domain/models/event.py` | Edit (add CorrectionPatternDetected) | C |
| `weebot/application/ports/state_repo_port.py` | Edit (add correction methods) | C |
| `weebot/infrastructure/persistence/sqlite_state_repo.py` | Edit (implement correction table) | C |
| `weebot/application/flows/states/executing.py` | Edit (wire tracker into retry path) | C |
| `weebot/application/flows/plan_act_flow.py` | Edit (wire event to behavioral learner) | C |
| `tests/unit/test_prompt_builder_scope.py` | New | A, B |
| `tests/unit/test_correction_tracker.py` | New | C |
| `tests/unit/test_architecture_fitness.py` | Edit (add fitness tests) | A, C |

## Non-Goals (Explicitly Skipped)

- **Filesystem-as-architecture**: weebot's SQLite + event-sourcing is strictly more capable. No regression.
- **Manual-only error recovery**: weebot already has automated replan. Keep it.
- **Sequential-only execution**: weebot already has concurrent pipelines. Keep it.
- **Custom context_refs per step**: YAGNI. The 4-scope enum covers 95% of cases. Add custom refs only if the enum proves insufficient after real usage.
- **LLM-based scope assignment**: The planner assigns scopes via prompt rules. No separate LLM call needed.
- **Cross-step consistency verification**: ICM's Verify section is interesting but overlaps with existing StepEvidenceAuditor. Defer until evidence shows auditor misses cross-step drift.
