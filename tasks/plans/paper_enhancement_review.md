# Self-Review — Paper Enhancement Roadmap

**Reviewed:** `tasks/plans/paper_enhancement_roadmap.md`
**Date:** 2025-07-17

---

## Verified Facts vs. Fabrications

### ❌ Fabricated claim

> "Weebot already covers ~80% of the paper's framework"

This is a **fabricated percentage** — no measurement was performed. It's
presented as a precise metric ("~80%") but is purely a gut estimate. Should
be replaced with a hedged statement: "Weebot has substantial coverage across
all four components, but gaps exist in specific implementation patterns."

### ⚠️ Overclaimed enhancement #5 (Set-of-Mark Visual Grounding)

I claimed: "Weebot has no Set-of-Mark visual grounding."

**Evidence contradicts this.** [VERIFIED] Weebot's `playwright_adapter.py:326-330`
already calls `element.bounding_box()` and returns `bounding_box` tuples.
`browser_inspector.py:80,167,309` already handles bounding box data in
tool results. The infrastructure for getting element coordinates exists.

**Correction:** Enhancement #5 should be re-scoped from "build SoM from scratch"
to "add visual overlay rendering on screenshots" — combine existing bounding
box data with screenshot capture to produce SoM-style annotated images.
The foundation exists; the missing piece is the rendering/labeling step.

### ⚠️ Overclaimed enhancement #4 (Multi-Expert Architecture)

I claimed: "No specialized expert agents exist."

**Evidence contradicts this.** [VERIFIED] `interface_customization.py:286`
has `ExpertiseBasedCustomizer`. `tool_registry.py` has `DEFAULT_ROLE_MAPPINGS`
with specialized role→tool assignments. The concept of "specialized agents
with different capabilities" exists.

**Correction:** Enhancement #4 is better framed as: "Formalize the existing
role-based approach into the paper's explicit Expert Profile model with
boundary rules and input/output schemas." It's an evolution, not a greenfield.

### ✅ Correct claim — enhancement #1 (AWM)

No Agent Workflow Memory exists. [VERIFIED] Search for `workflow.memory`,
`AWM`, `induced.workflow` returned only unrelated workflow_orchestrator
matches (DAG execution, not memory-based workflow reuse). This is a genuine gap.

### ✅ Correct claim — enhancement #2 (DPPM)

No parallel plan generation with merge exists. [VERIFIED] Search for
`parallel.plan`, `DPPM`, `decompose.*plan.*merge` returned zero matches
across 725 files. This is a genuine gap.

### ✅ Correct claim — enhancement #3 (3-tier failure classification)

Weebot has `classify_tool_error` in `_error_handler.py:110` which classifies
error **types** (timeout, auth_failure, etc.) but does NOT classify failure
**severity** (minor fix vs subplan replan vs full replan). The paper's 3-tier
model is a genuine gap.

### ✅ Correct enhancement #6 (Trajectory Consolidation)

No trajectory merging/consolidation exists. `memory_dedup.py` handles
general dedup but not trajectory-specific consolidation.

### ✅ Correct enhancement #7 (One-Shot Learning)

No demonstration recording or one-shot learning mechanism exists.

### ✅ Correct enhancement #8 (Parallel Tool Execution)

PlanActFlow processes steps sequentially. No `asyncio.gather` for independent
steps. Genuine gap.

---

## Revised Assessment Table

| Enhancement | Original Claim | Verification | Revised |
|-------------|---------------|-------------|---------|
| 1 — AWM | Genuine gap | ✅ VERIFIED | Keep as-is |
| 2 — DPPM | Genuine gap | ✅ VERIFIED | Keep as-is |
| 3 — 3-Tier Failure | Genuine gap | ✅ VERIFIED (error types exist, severity tiers don't) | Keep as-is, note existing `classify_tool_error` as foundation |
| 4 — Multi-Expert | No experts exist | ❌ OVERCLAIMED — `ExpertiseBasedCustomizer` + role registry exist | Reframe as "formalize into Expert Profile model" |
| 5 — Set-of-Mark | No SoM exists | ❌ OVERCLAIMED — bounding box infrastructure exists | Reframe as "add screenshot overlay rendering" |
| 6 — Trajectory Consolidation | Genuine gap | ✅ VERIFIED | Keep as-is |
| 7 — One-Shot Learning | Genuine gap | ✅ VERIFIED | Keep as-is |
| 8 — Parallel Execution | Genuine gap | ✅ VERIFIED | Keep as-is |

---

## Additional Issue — No Evidence Metrics

The roadmap includes impact claims like:
- "Should improve browser task success rate by 10–20%"
- "Directly addresses the paper's limitation"
- "Reduces planning latency for recurring task types"

None of these are grounded in measurements. They are projections, not facts.
Every impact estimate should be tagged [HYPOTHESIS] and the improvement
targets should be tied to benchmark metrics that would actually measure them.

---

## Priority Re-Ordering After Review

Given that #5 has existing foundation and #4 has partial coverage:

1. **AWM** (#1) — still highest priority, greenfield, highest impact
2. **3-Tier Failure** (#3) — builds on existing `classify_tool_error`, quick win
3. **DPPM** (#2) — greenfield, high complexity, but highest reasoning gain
4. **SoM Overlay** (#5 revised) — build on existing bounding boxes, quick visual win
5. **Expert Formalization** (#4 revised) — evolution of existing role registry
6. **Trajectory Consolidation** (#6) — depends on AWM
7. **Parallel Execution** (#8) — depends on DPPM for parallel plans to execute
8. **One-Shot Learning** (#7) — highest effort, lowest immediate ROI
