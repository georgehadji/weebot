# Ponytail Harness Block — Implementation Plan

**Source:** https://github.com/DietrichGebert/ponytail (MIT, 36.2k stars)
**Target:** Inject ponytail's 6-rung YAGNI ladder into weebot's executor harness
**Architecture:** Clean Architecture — domain models → application service → infrastructure adapter
**Test baseline:** 268 passed, 54 skipped, 0 failures

---

## What Ponytail Is and Why It Fits Weebot

Ponytail is a coding-assistant skill that forces AI agents to climb a 6-rung decision ladder before writing any code. It achieves ~54% less lines of code, ~22% fewer tokens, and ~27% faster execution. Every rung asks "can I do less?" — which is exactly what weebot's architecture remediation (1,414→803 lines, 4→2 zero-impl ports) already applied as static design decisions.

**The gap:** Weebot's executor currently makes tool calls based on the plan without a runtime YAGNI check. Each unnecessary tool call costs 500-2000 tokens of context window. The ponytail harness block closes this gap by inserting a pre-flight check before each step.

**Key design constraint:** Ponytail governs *what the agent builds*, not how fast it builds. In weebot, "what is built" = the sequence of tool calls in a step. The harness block filters those tool calls through the ladder — each call must survive the rungs.

---

## Architecture Integration Points

```
weebot/config/harness/ponytail_ladder.yaml     ← the ladder text (data)
    ↓
weebot/domain/models/harness_instructions.py   ← InstructionConfig.yagni_preflight field
    ↓
weebot/application/services/harness_prompt_assembler.py  ← assembles ladder into prompt
    ↓
weebot/application/agents/executor/_base.py    ← executor receives harness instruction block
    ↓
every ExecutorAgent tool call passes through the ladder
```

The integration touches four layers but only adds one field, one YAML file, and ~15 lines of assembly logic. Zero new classes, zero new ports, zero new DI registrations.

---

## Phase 1: Domain Model Extension (10 minutes)

### Step 1.1 — Add `yagni_preflight` to `InstructionConfig`

**File:** `weebot/domain/models/harness_instructions.py`

Add a new field:

```python
class InstructionConfig(BaseModel):
    # ... existing fields ...

    yagni_preflight: str = Field(
        default=(
            "Before executing any step, stop at the first rung that holds:\n"
            "1. Does this step still need to be executed?\n"
            "   Previous steps may have covered it. If so, skip this step and note why.\n"
            "2. Does an existing tool call in the conversation already cover this?\n"
            "   Reuse its output instead of repeating the call.\n"
            "3. Can a single bash/python command replace the planned sequence?\n"
            "   One command is cheaper than three tool calls.\n"
            "4. Will the tool call output be smaller than the code it would produce?\n"
            "   If the output is a single line, just output it. Don't call a tool.\n"
            "5. Is the tool call necessary at all?\n"
            "   Only then: execute the planned step.\n"
            "\n"
            "After execution, append 'skipped: [X], add when [Y]' if you skipped anything.\n"
            "Never skip: validation, error handling, security checks, or accessibility."
        ),
        description=(
            "Ponytail YAGNI ladder — forces the agent to question whether each "
            "step needs to be executed, from 'skip entirely' (rung 1) to 'execute "
            "as planned' (rung 5). Based on the ponytail skill (github.com/DietrichGebert/ponytail)."
        ),
    )
```

**Rationale:**
- Default value includes the ladder text inline, so no config file is required to get the benefit
- The `harness_config.yaml` in `weebot/config/harness/` can override this field for model-specific tuning
- Pydantic `Field(default=...)` means all existing `InstructionConfig` instances automatically get this behavior

**Verification:**
```python
from weebot.domain.models.harness_instructions import InstructionConfig
c = InstructionConfig()
assert len(c.yagni_preflight) > 100  # has default
assert "rung" in c.yagni_preflight   # contains the ladder
```

---

## Phase 2: Harness Assembler Update (10 minutes)

### Step 2.1 — Add yagni_preflight to BLOCK_TEMPLATE

**File:** `weebot/application/services/harness_prompt_assembler.py`

Update `BLOCK_TEMPLATE` to include the pre-flight section:

```python
BLOCK_TEMPLATE = (
    "\n\n## Pre-Flight Check (YAGNI)\n\n"
    "{yagni_preflight}\n\n"
    "# # Harness Instructions (model-specific)\n\n"
    "{bootstrap_section}"
    "{execution_section}"
    "{verification_section}"
    "{failure_recovery_section}"
    "{extension_section}"
)
```

Update `assemble()` to accept and format the field:

```python
@classmethod
def assemble(
    cls,
    instructions: InstructionConfig | None = None,
    # ... existing params ...
) -> str:
    yagni = instructions.yagni_preflight if instructions else ""
    # ... existing logic ...
    return cls.BLOCK_TEMPLATE.format(
        yagni_preflight=yagni,
        # ... existing format args ...
    )
```

**Rationale:**
- Pre-flight check goes BEFORE harness instructions — it gates whether execution happens at all
- The existing `bootstrap` field is "what to do on first action"; `yagni_preflight` is "should we do anything at all"
- Using `.format(**kwargs)` keeps the template readable

**Verification:**
```python
from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
from weebot.domain.models.harness_instructions import InstructionConfig
block = HarnessPromptAssembler.assemble(instructions=InstructionConfig())
assert "Pre-Flight Check" in block
assert "rung" in block
```

---

## Phase 3: Harness Config File (5 minutes)

### Step 3.1 — Create ponytail harness config

**File:** `weebot/config/harness/ponytail.yaml`

```yaml
# Ponytail YAGNI harness — default pre-flight check for all executor steps
# Based on github.com/DietrichGebert/ponytail (MIT)
instructions:
  yagni_preflight: |
    BEFORE executing any step, stop at the first rung that holds:

    1. YAGNI — does this step need to exist at all?
       Previous steps may have satisfied it. If so, say "skipped: covered by [previous step]"
       and move on without a tool call.

    2. STDLIB — does the Python standard library or a built-in shell command cover this?
       Use `python_execute` with stdlib imports instead of installing a package.
       Use shell built-ins (`grep`, `sed`, `awk`) instead of custom scripts.

    3. NATIVE — does the platform already provide this?
       Browser has <input type="date">, filesystem has os.path, SQLite has constraints.
       Don't build what the runtime already gives you.

    4. DEPENDENCY — does an already-installed package solve this?
       `pip list` before `pip install`. Never add a new dependency for what a few lines can do.

    5. ONE-LINE — can this be a single command or expression?
       One `bash` call instead of a `file_editor` write + `python_execute` run.
       One `file_editor` edit instead of three sequential edits.

    6. MINIMUM — only then: execute the planned step.
       Write the shortest code that works. No scaffolding, no "for later," no config for
       values that never change. The best code is the code never written.

  execution: |
    After each tool call, if you skipped anything, append a one-line note:
    "skipped: [what was skipped] — add when [condition that would justify it]"

    Mark deliberate simplifications with a `ponytail:` comment so future readers
    know it was intentional, not ignorant:
    ```
    # ponytail: global lock, per-account locks if throughput matters
    ```

runtime_control:
  enabled: true
  max_recent_tool_errors: 3
  max_total_tool_messages: 20
```

**Rationale:**
- Separate from the default inline text so Self-Harness can evolve it independently
- The harness config's `execution` field reinforces the ladder with the comment convention
- Runtime control keeps safety guards — ponytail never disables validation

---

## Phase 4: DI Wiring (10 minutes)

### Step 4.1 — Register ponytail as the default harness

**File:** `weebot/application/di/__init__.py`

In `configure_defaults()`, ensure the harness resolver loads ponytail:

```python
def configure_defaults(self, ...):
    # ... existing wiring ...
    # Ponytail YAGNI harness — default for all executor sessions
    self.register("harness_resolver", lambda: self._create_harness_resolver())
```

The `ModelAwareHarnessResolver` already knows how to load harness configs from `weebot/config/harness/`. No DI changes needed if the default config already points to `ponytail.yaml`. Check `_create_harness_resolver()` in `_factories.py`.

**Verification:**
```python
c = Container()
c.configure_defaults()
resolver = c.get("harness_resolver")
cfg = resolver.resolve("default")  # or whatever key
assert cfg is not None
assert len(cfg.instructions.yagni_preflight) > 0
```

---

## Phase 5: Architecture Fitness Test (5 minutes)

### Step 5.1 — Test that ponytail harness block is present

**File:** `tests/unit/test_architecture_fitness.py`

```python
def test_ponytail_harness_block_present():
    """The ponytail YAGNI ladder must be part of InstructionConfig defaults."""
    from weebot.domain.models.harness_instructions import InstructionConfig
    cfg = InstructionConfig()
    assert "rung" in cfg.yagni_preflight, "Missing rung ladder"
    assert "YAGNI" in cfg.yagni_preflight, "Missing YAGNI keyword"
    assert "never skip" in cfg.yagni_preflight.lower(), "Missing safety clause"


def test_ponytail_harness_assembled():
    """The harness assembler must include yagni_preflight in output."""
    from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
    from weebot.domain.models.harness_instructions import InstructionConfig
    block = HarnessPromptAssembler.assemble(instructions=InstructionConfig())
    assert "Pre-Flight" in block
    assert "rung" in block
```

---

## Phase 6: Integration Verification (5 minutes)

### Step 6.1 — End-to-end import and instantiation test

```python
# Verify the full chain: domain model → assembler → executor integration
from weebot.domain.models.harness_instructions import InstructionConfig
from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
from weebot.application.services.model_aware_harness_resolver import ModelAwareHarnessResolver

# 1. Default config has the ladder
cfg = InstructionConfig()
assert len(cfg.yagni_preflight) > 100

# 2. Assembler includes it
block = HarnessPromptAssembler.assemble(instructions=cfg)
assert "Pre-Flight Check" in block

# 3. Resolver can load it from config
import yaml, pathlib
ponytail_yaml = pathlib.Path("weebot/config/harness/ponytail.yaml")
if ponytail_yaml.exists():
    data = yaml.safe_load(ponytail_yaml.read_text())
    loaded = InstructionConfig(**data.get("instructions", {}))
    assert "rung" in loaded.yagni_preflight
```

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Ladder text too long, bloats prompt | Medium | Low | Ladder is ~300 tokens — negligible against 128k context window |
| Agent over-applies Rung 1 (skips everything) | Low | Medium | Safety clause ("never skip: validation, error handling, security checks") plus `StepBudget` prevents infinite skip loops |
| Harness config file not found on fresh install | Low | Medium | Default value in `InstructionConfig` falls back to inline ladder text |
| Self-Harness optimizer mutates safety clause | Low | High | `RuntimeControlConfig` gate prevents autonomous modification of guardrails |

---

## Definition of Done

- [ ] `InstructionConfig.yagni_preflight` field added with default ladder text
- [ ] `HarnessPromptAssembler.BLOCK_TEMPLATE` includes `{yagni_preflight}`
- [ ] `weebot/config/harness/ponytail.yaml` created
- [ ] 2 architecture fitness tests pass
- [ ] Full import chain verified (domain → assembler → resolver)
- [ ] All existing tests pass (268 pass, 54 skip, 0 fail)

---

## Estimated Effort

| Phase | Description | Time |
|---|---|---|
| 1 | Domain model: add `yagni_preflight` field | 10 min |
| 2 | Assembler: update template + assembly logic | 10 min |
| 3 | Config: create `ponytail.yaml` | 5 min |
| 4 | DI: verify wiring (likely zero changes) | 10 min |
| 5 | Tests: 2 fitness tests | 5 min |
| 6 | Integration verification | 5 min |
| **Total** | | **45 minutes** |

---

## Phase 7: Ponytail Conciseness Review (30 minutes)

### Goal: Close the tool-output gap — review step outputs for over-engineering

**The gap:** Phase 1's harness block gates *tool calls* through the ladder before execution. But the code generated *inside* a `file_editor` or `python_execute` call isn't constrained — it happens inside the tool, not in the executor's prompt context.

**The fix:** Weebot already has a `ReviewingState` that runs after every code-producing step. It uses `CodeReviewerPort` → `CodeReviewerService` to review step outputs and can force a `revise` (re-run the step with a hint) or `reject` (trigger replanning). Adding "over-engineered" as a review dimension gives the agent a second chance to simplify bloated output.

**Architecture integration:**

```
weebot/domain/models/code_review.py          ← CodeReviewResult.over_engineered field
    ↓
weebot/application/services/code_reviewer_service.py  ← add conciseness to review prompt
    ↓
weebot/application/flows/states/reviewing.py  ← already processes CodeReviewResult.issues
    ↓
every ExecutorAgent step output is reviewed for over-engineering
```

No new ports, no new services, no new flow states. One domain field + one prompt edit.

### Step 7.1 — Add `over_engineered` to `CodeReviewResult`

**File:** `weebot/domain/models/code_review.py`

```python
class CodeReviewResult(BaseModel):
    # ... existing fields ...

    over_engineered: bool = Field(
        default=False,
        description=(
            "True if the step output uses more code, files, or dependencies "
            "than necessary. Reviewer applies the ponytail 6-rung ladder to "
            "the output code: was an abstraction added unnecessarily (rung 1)? "
            "Could stdlib have replaced custom code (rung 2)? Did the step "
            "install a new dependency for a one-liner (rung 4)?"
        ),
    )
```

### Step 7.2 — Add conciseness dimension to the code reviewer prompt

**File:** `weebot/application/services/code_reviewer_service.py`

Append to the review system prompt:

```python
_REVIEW_SYSTEM_PROMPT = """...existing prompt...

6. OVER-ENGINEERING (ponytail ladder):
   - Was an abstraction added with only one implementation? → flag as over_engineered
   - Could a stdlib function replace custom code? → flag as over_engineered
   - Was a new dependency installed for something a few lines could do? → flag as over_engineered
   - Was a file created that only contains a one-liner the invoking code could inline? → flag as over_engineered
   - Did the step produce more than 3 files for a single concern? → flag as over_engineered

...existing response format + new field: over_engineered: bool...
"""
```

### Step 7.3 — Reviewer hint includes simplification

When `over_engineered=True` and `verdict="revise"`, append to the hint:

```python
if result.over_engineered:
    result.hint += " Simplify to the shortest correct version. "
    result.hint += "One file if possible, one function if possible, one line if possible."
```

### Step 7.4 — Architecture fitness test

```python
def test_code_review_result_has_over_engineered():
    """CodeReviewResult must include over_engineered field."""
    from weebot.domain.models.code_review import CodeReviewResult
    r = CodeReviewResult()
    assert hasattr(r, "over_engineered"), "Missing over_engineered field"
    assert r.over_engineered == False  # default is False

def test_code_review_prompt_includes_conciseness():
    """Code reviewer prompt must check for over-engineering."""
    from weebot.application.services.code_reviewer_service import _REVIEW_SYSTEM_PROMPT
    assert "over_engineered" in _REVIEW_SYSTEM_PROMPT.lower() or "OVER-ENGINEERING" in _REVIEW_SYSTEM_PROMPT
```

### Step 7.5 — End-to-end integration test

```python
# Verify the review pipeline: domain model → reviewer → result
from weebot.domain.models.code_review import CodeReviewResult
from weebot.application.services.code_reviewer_service import CodeReviewerService

result = CodeReviewResult()
assert hasattr(result, "over_engineered")

# With a real LLM: reviewer should flag bloated code
# (integration test, gated behind WEEBOT_INTEGRATION_TESTS=1)
```

---

## Complete Architecture Map

```
┌─────────────────────────────────────────────────────────┐
│                    PLAN-ACT FLOW                         │
│                                                         │
│  PlanningState → ExecutingState                         │
│                      │                                  │
│                      │ every step:                      │
│                      ├── HarnessBlock (Phase 1)         │
│                      │   YAGNI ladder: should I         │
│                      │   call this tool at all?         │
│                      │                                  │
│                      ├── CascadeExecutor                │
│                      │   LLM generates tool calls       │
│                      │                                  │
│                      ├── ToolExecutor                   │
│                      │   Executes tool calls            │
│                      │                                  │
│                      ▼                                  │
│              ReviewingState (Phase 2)                   │
│                      │                                  │
│                      ├── CodeReviewerService            │
│                      │   reviews step output for:       │
│                      │   • correctness                  │
│                      │   • security                     │
│                      │   • over_engineering (NEW)       │
│                      │                                  │
│                      ├── approved → next step           │
│                      ├── revise   → re-run with hint    │
│                      └── reject   → replan              │
└─────────────────────────────────────────────────────────┘
```

## Updated Definition of Done

- [ ] `InstructionConfig.yagni_preflight` field with default ladder text
- [ ] `HarnessPromptAssembler.BLOCK_TEMPLATE` includes `{yagni_preflight}`
- [ ] `weebot/config/harness/ponytail.yaml` created
- [ ] `CodeReviewResult.over_engineered` field added
- [ ] `CodeReviewerService` conciseness prompt added
- [ ] 4 architecture fitness tests pass
- [ ] Full import chain verified (domain → assembler → resolver → reviewer)
- [ ] All existing tests pass (268 pass, 54 skip, 0 fail)

## Updated Effort Estimate

| Phase | Description | Time |
|---|---|---|
| 1 | Domain model: add `yagni_preflight` field | 10 min |
| 2 | Assembler: update template + assembly logic | 10 min |
| 3 | Config: create `ponytail.yaml` | 5 min |
| 4 | DI: verify wiring | 10 min |
| 5 | Tests: 2 fitness tests | 5 min |
| 6 | Integration verification | 5 min |
| 7 | Conciseness review: domain + prompt + tests | 30 min |
| **Total** | | **75 minutes** |

## What We're Still Not Doing (and Why)

| Skipped | Reason |
|---|---|
| SkillOpt ponytail scoring | No evidence that trajectory data alone drives conciseness. Ponytail's ladder is a prompt, not a training signal. |
| `/ponytail` CLI commands | Weebot already has code-review. Ponytail-review is a different flavor of the same tool. |
| Skill Hub registration | Documentation, not architecture. |
| Multiple intensity levels (lite/full/ultra) | Premature abstraction. Start with "full" (the default), add levels when user data shows demand. |
| PlanCritic conciseness check | `PlanCritic` reviews plans (before execution) — "is this plan necessary?" The harness block already covers this. `CodeReviewer` reviews outputs (after execution) — "was this output bloated?" This is the complementary pass. |
