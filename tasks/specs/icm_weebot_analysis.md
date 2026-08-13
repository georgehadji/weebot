# ICM (Interpretable Context Methodology) vs Weebot — Gap Analysis

**Paper**: Van Clief & McDermott, "Interpretable Context Methodology: Folder Structure as Agent Architecture" (March 2026, Eduba / University of Edinburgh)
**Date**: 2026-08-13

## Paper Core Thesis

Replace framework-level agent orchestration with filesystem structure. Numbered folders = stages. Markdown files = prompts and context. Plain text = universal interface. One agent reads different context at each stage instead of multiple agents coordinating through code.

Five-layer context hierarchy:
- **Layer 0**: Global identity (CLAUDE.md) — "Where am I?"
- **Layer 1**: Workspace routing (CONTEXT.md) — "Where do I go?"
- **Layer 2**: Stage contracts (per-stage CONTEXT.md) — "What do I do?" with explicit Inputs/Process/Outputs
- **Layer 3**: Reference material (stable across runs) — "What rules apply?" (voice, style, conventions)
- **Layer 4**: Working artifacts (per-run) — "What am I working with?" (previous stage output)

Key insight: each stage gets 2,000–8,000 focused tokens vs 30,000–50,000 in a monolithic prompt. Avoids "lost in the middle" degradation.

## What Weebot Already Has (≈ or >)

| ICM Concept | Weebot Equivalent | Status |
|---|---|---|
| Layer 0 identity | CLAUDE.md + config | ✅ Covered |
| Stage decomposition | Plan → Steps (PlanActFlow) | ✅ Covered |
| Plain text artifacts | Session events, SQLite event store | ✅ Covered (richer) |
| Reference material | Skill files (SKILL.md), user model, behavioral rules | ✅ Covered |
| Working artifacts | Step results, tool events, conversation history | ✅ Covered |
| Git-compatible | Yes | ✅ |
| Acceptance criteria | Step.acceptance_criteria + StepEvidenceAuditor | ✅ Covered (LH-Harness) |
| Evidence provenance | Step.evidence_refs | ✅ Covered |
| Multi-model delegation | CascadeExecutor, model routing | ✅ Ahead (ICM uses single model family) |
| Automated error recovery | Plan-Act-Update loop, replanning | ✅ Ahead (ICM relies on manual re-run) |
| Concurrent execution | Task pipeline orchestrator | ✅ Ahead (ICM is sequential-only) |

## What ICM Adds That Weebot Lacks — 3 Gaps

### Gap 1: Per-Step Context Scoping (HIGH VALUE)

**ICM**: Each stage's CONTEXT.md declares an explicit **Inputs table** — exactly which files from Layers 3 and 4 to load. Stage 2 might load `voice.md` + `output/research.md`; stage 3 might load `design-system.md` + `output/script.md`. No stage loads everything.

**Weebot**: `build_executor_prompt()` in `_prompt_builder.py` assembles the **same context blob for every step**: base prompt + harness block + all matched skills + behavioral rules + user profile + personality. Whether the step is "research competitors" or "write a unit test", it gets the same user profile, the same personality injection, the same behavioral rules.

**Why it matters**: The paper cites Liu et al. showing significant performance degradation when relevant information is buried in irrelevant context. Weebot's executor prompt can exceed 4,000 tokens of boilerplate before the step description even appears. A step that just needs to run a shell command doesn't need the user profile. A step that writes prose doesn't need the PowerShell syntax reminder.

**Concrete fix**: Add a `context_scope` field to `Step` that declares what context sources this step needs. The prompt builder selects accordingly:

```python
class ContextScope(str, Enum):
    FULL = "full"          # all sources (default, backward compat)
    MINIMAL = "minimal"    # base prompt only
    SKILL = "skill"        # base + matched skill
    CREATIVE = "creative"  # base + user profile + personality + voice

class Step(BaseModel):
    context_scope: ContextScope = ContextScope.FULL
    context_refs: List[str] = []  # explicit layer-3 refs if scope is custom
```

The planner would assign scopes at plan time. Token savings: 30–60% per step for minimal-context steps.

### Gap 2: Reference vs Working Separation in Prompt (MEDIUM VALUE)

**ICM**: Formally separates Layer 3 (reference = "internalize as constraints") from Layer 4 (working = "process as input") in the context window. The model receives structurally separated context, which gives clearer signals about what constrains vs what to transform.

**Weebot**: Everything goes into a flat `parts: list[str]` and gets joined with `"\n"`. Skill content, user profile, behavioral rules, and the step description are all concatenated without structural markers. The model has to figure out which parts are constraints vs input.

**Concrete fix**: Structure the prompt into labeled sections:

```
## CONSTRAINTS (internalize these as rules)
{skills, behavioral rules, user profile, conventions}

## TASK (transform this input)
{step description, prior step results, working material}
```

This is a prompt-engineering change — no architecture needed, just restructuring how `build_executor_prompt` concatenates `parts[]`.

### Gap 3: Recurring Correction → Source Improvement Loop (HIGH VALUE)

**ICM** (Section 6.3 — "Edit-Source Principle"): When a human repeatedly makes the same kind of edit to stage output (e.g., always tightens the opening paragraph), surface that pattern and suggest a source-level change (update the stage contract or reference material). "Editing the output fixes this run. Editing the source fixes every future run."

**Weebot**: When the PlanActFlow replans after failure, or when the human corrects output, the correction is one-off. Nothing tracks *what kinds* of corrections recur. The behavioral_learner captures explicit rules but not patterns from repeated output edits. The skill promotion loop (identified as broken in prime-agent audit) means corrections never flow back into skill files.

**This connects two prior audit findings**:
- **Prime Agent audit**: "missing quarantined→candidate promoter makes the entire skill-distillation loop dead"
- **LongHorizon-Harness audit**: weebot's executor is its own completion authority — no external verification of consistency across steps

**Concrete fix**: Add a `CorrectionTracker` service:
1. When a plan step fails and gets re-executed, or when replanning occurs, record the *diff* between the failed output and the successful output
2. After N runs, surface recurring correction patterns (e.g., "step 3 always gets corrected for tone" → suggest updating the voice skill)
3. Wire this into the existing (but broken) skill promotion pipeline as a signal source

This closes the feedback loop that both prior audits identified as the biggest dead code path.

## What ICM Lacks That Weebot Has

- **Automated error recovery**: ICM requires manual re-run of failed stages. Weebot replans automatically.
- **Dynamic branching**: ICM is sequential by design. Weebot's flow router handles branching.
- **Concurrent execution**: ICM is sequential. Weebot has pipeline orchestration.
- **Model cascading**: ICM uses one model family. Weebot cascades free → budget → premium.
- **Memory persistence**: ICM workspaces are ephemeral folders. Weebot has persistent memory, user model, session history.
- **Evidence-gated completion**: ICM relies on human review gates. Weebot has StepEvidenceAuditor (automated).
- **Tool safety**: ICM has no bash guard equivalent.

## Verdict

ICM is a simpler paradigm targeting a different audience (non-developers running sequential content pipelines). Weebot is architecturally ahead on orchestration, error recovery, memory, and safety.

But ICM's context-engineering insights are directly portable:

| Priority | Gap | Effort | Impact |
|---|---|---|---|
| **P0** | Per-step context scoping | Medium (Step model + prompt builder) | 30-60% token savings, better step output quality |
| **P1** | Recurring correction → source improvement | Medium (new service + wire to skill promotion) | Closes the biggest dead loop in weebot |
| **P2** | Reference/Working prompt separation | Low (prompt builder refactor) | Better constraint adherence in creative steps |

**RL not portable**: ICM has no learning/adaptation mechanism at all — it's purely static configuration.
**Filesystem-as-architecture not portable**: Weebot's SQLite + event-sourced architecture is strictly more capable than folders-on-disk. No regression to adopt.
