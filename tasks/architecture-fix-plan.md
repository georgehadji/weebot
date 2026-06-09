# Architecture-Level Fix Plan — 11 Problems

> **Architecture:** Clean Architecture (Hexagonal) — Domain → Application → Infrastructure → Interfaces
> **Rule:** Dependencies point inward. Domain remains pure. Infrastructure implements ports defined in Application.

---

## Problem Map by Layer

| Layer | Problems |
|-------|----------|
| **Application — Planner** | #3 (identical plans), #4 (#7 output location), #5 (external CSS), #9 (no Output/ convention), #10 (single-file enforcement) |
| **Application — Executor** | #1 (PowerShell override), #2 (step failure after abort), #7 (system prompt priority) |
| **Application — PlanNovelty** | #8 (warns only, never blocks) |
| **Infrastructure — Tools** | #6 (svg templates), #11 (image_gen monotony) |
| **Infrastructure — System Prompt** | #1, #7 (training data overrides) |

---

## Fix 1: Planner Prompt — Hard Constraints (Application Layer)

**Problems:** #4 (output location), #5 (external CSS), #9 (no Output/ convention), #10 (single-file enforcement)

**File:** `weebot/config/prompts/planner_system.txt`

**Root cause:** The planner prompt has "STEP BUDGET" rules but no output-path or self-contained rules. The LLM defaults to creating separate CSS/JS files and placing output in arbitrary locations.

**Fix:** Add an `OUTPUT CONSTRAINTS` section after STEP BUDGET:

```
OUTPUT CONSTRAINTS (invariant — never violate):
- ALL generated files MUST go under Output/<project-name>/ (e.g. Output/portfolio/).
  Never create files in the workspace root.
- Websites MUST be a single self-contained index.html with embedded <style>
  and <script> tags. NO external .css, .js, .svg, or .png references.
  Exception: image_gen output may produce .png/.svg files referenced as
  local assets within the same Output/<project-name>/ directory.
- Use inline SVG data URIs for icons instead of separate files.
- Use image_gen for hero/project images only — inline everything else.
```

**Architecture:** Application layer — planner system prompt. No code changes needed.

---

## Fix 2: PlanNoveltyTracker — Block, Don't Warn (Application Layer)

**Problems:** #3 (identical plans), #8 (warns only)

**Files:** `weebot/application/services/plan_novelty.py`, `weebot/application/flows/plan_act_flow.py:225-237`

**Root cause:** `is_too_similar()` returns a bool, but the caller (`_snapshot_plan()` in plan_act_flow.py) only logs a warning and continues. This lets identical plans loop through execution.

**Fix (2 changes):**

| Step | File | Change |
|------|------|--------|
| A | `plan_act_flow.py:225-237` | When `is_too_similar` returns True, inject `avoidance_prompt()` into the planner context BEFORE the next plan creation, and increment a `_similar_plan_count`. If `_similar_plan_count >= 3`, raise `PlanStuckError` and terminate the flow with a clear message |
| B | `plan_novelty.py` | Add `avoidance_prompt()` return value to the `PlanNoveltyTracker` public API — currently only used in the fallback path of `UpdatingState`, not the CQRS path |

```python
# plan_act_flow.py — _snapshot_plan():
if self._plan_history.is_too_similar(self._plan, threshold=0.7, window=3):
    self._similar_plan_count += 1
    if self._similar_plan_count >= 3:
        raise PlanStuckError(
            "Plan is stuck: 3 consecutive plans with fingerprint similarity > 0.7. "
            "The task may need human intervention or a different approach."
        )
    # Inject diversity hints for next planner call
    self._diversification_hint = self._plan_history.get_novelty().avoidance_prompt()
    logger.warning(
        "Plan fingerprint too similar (attempt %d/3) — injecting diversity hints",
        self._similar_plan_count,
    )
```

**Architecture:** Application layer — modifies flow state machine behavior. No Domain changes. The `PlanStuckError` is a new Application-layer exception.

---

## Fix 3: System Prompt Priority — PowerShell Boot Message (Application Layer)

**Problems:** #1 (PowerShell table ineffective), #7 (LLM training data overrides)

**Files:** `weebot/application/agents/executor.py` (system message construction), `WEEBOT_CORE.md`

**Root cause:** The PowerShell table in WEEBOT_CORE.md is buried in the middle of a 4891-char personality file. The LLM's training data (Unix-native) dominates because the table is just informational text, not an instruction. The LLM needs a **strong, repeated** directive at the top of every conversation.

**Fix (2 changes):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/application/agents/executor.py` | Add a `BOOT_MESSAGE` constant injected as the FIRST system message in every conversation. Format: `"CRITICAL: You are running on Windows 11 with PowerShell 5.1. All shell commands MUST use PowerShell syntax. ls -la → Get-ChildItem. mkdir -p → New-Item -Force. Never use Unix commands. Re-read the PowerShell table in WEEBOT_CORE.md before every shell call."` |
| B | `WEEBOT_CORE.md` | Move the PowerShell table to the TOP of the file, right after `<identity>`. Add a `## CRITICAL: Shell Environment` header. Make it the first thing the LLM reads. |

```python
# executor.py — in __init__ or system message construction:
_BOOT_MESSAGE = (
    "You are running on Windows 11 with PowerShell 5.1. "
    "ALL shell commands MUST use PowerShell-native syntax:\n"
    "  ls -la <dir>  →  Get-ChildItem <dir>\n"
    "  mkdir -p <dir> →  New-Item -ItemType Directory -Force -Path <dir>\n"
    "  rm -rf <dir>  →  Remove-Item -Recurse -Force <dir>\n"
    "  cat <file>    →  Get-Content <file>\n"
    "  && chains     →  ; (semicolons)\n"
    "  Never use Unix commands — they WILL fail."
)
# Prepend to system message list
self._conversation_buffer.insert(0, {
    "role": "system",
    "content": _BOOT_MESSAGE,
})
```

**Architecture:** Application layer — executor agent construction. The BOOT_MESSAGE is a cross-cutting concern, not business logic. No Domain changes.

---

## Fix 4: Step Granularity — Max Tokens Per Step Description (Application Layer)

**Problems:** #2 (step auto-abort works but step still fails — too many images in one step)

**Files:** `weebot/application/agents/planner.py` (`_parse_plan()`), `weebot/config/constants.py`

**Root cause:** The planner generates monolithic steps like "Create all required images as SVG files: hero.svg, og.svg, project1.svg ... project4.svg, skill-node.svg, ..." — 12+ files in one step. The executor can't handle this because each file requires 2-3 tool calls. The step hits the trajectory monitor's SEMANTIC_LOOP detection and aborts.

**Fix (2 changes):**

| Step | File | Change |
|------|------|--------|
| A | `weebot/config/constants.py` | Add `MAX_ITEMS_PER_STEP: int = 5` — maximum number of discrete items (files, images, operations) a single step should describe |
| B | `weebot/application/agents/planner.py:_parse_plan()` | Add a heuristic: count commas + "and" in step description. If it lists more than `MAX_ITEMS_PER_STEP` items, split the step into multiple steps with numbered suffixes. |

```python
# In _parse_plan(), after building steps:
_final_steps = []
for step in steps:
    # Heuristic: count listed items in description
    items = len(re.findall(r'\b(?:hero|project\d|skill-|icon-|og-|profile|avatar)[\w.-]*', step.description, re.I))
    if items > MAX_ITEMS_PER_STEP:
        # Split into sub-steps: "Create images: hero.svg" "Create images: project1.svg" etc.
        _final_steps.append(Step(id=step.id, description=f"Generate images batch 1 (first {MAX_ITEMS_PER_STEP} items)", ...))
        _final_steps.append(Step(id=f"{step.id}-b", description=f"Generate images batch 2 (remaining items)", ...))
    else:
        _final_steps.append(step)
```

**Architecture:** Application layer — plan parsing. Heuristic only; doesn't change domain models. Constants in config layer.

---

## Fix 5: SVG Template Variety (Infrastructure Layer)

**Problems:** #6 (SVG images are tiny templates), #11 (image_gen 'svg' kind always returns template)

**Files:** `weebot/tools/image_gen_tool.py`

**Root cause:** The `_generate_ai` method's SVG fallback (lines 312-332) uses a single hardcoded SVG template. Every call with `kind='svg'` or `kind='ai'` (when APIs are unavailable) produces the same 691-byte gradient+text placeholder regardless of the prompt.

**Fix:** Replace the single template with a **prompt-driven parameterized template**. Extract colors, text, and theme from the prompt and vary the SVG structure.

```python
# NEW: prompt-driven SVG generation
@staticmethod
def _svg_from_prompt(prompt: str, width: int, height: int) -> str:
    """Generate a prompt-specific SVG using parameterized templates."""
    themes = {
        "hero": "large centered title with decorative geometry",
        "project": "card-style with icon grid and label",
        "icon": "circular badge with accent ring",
        "profile": "avatar frame with initials",
        "og": "banner with centered text blocks",
    }
    # Extract color hints from prompt
    colors = _extract_colors_from_prompt(prompt) or ["#1a1a2e", "#e94560", "#ffffff"]
    # Pick template based on prompt keywords
    template = _pick_svg_structure(prompt, themes)
    # Fill with prompt-derived values
    return template.render(colors=colors, text=_extract_title(prompt), ...)
```

**Architecture:** Infrastructure layer — pure tool implementation. No port changes needed. The existing `_generate_ai()` fallback already returns SVG strings; this just makes them variable.

---

## Fix 6: Output Convention — Planner Prompt Injection (Application Layer)

**Problems:** #4 (site output goes to wrong location)

**Files:** `weebot/config/prompts/planner_system.txt` (covered by Fix 1), `WEEBOT_CORE.md`

**Root cause:** The planner doesn't have a hard rule for output paths. The LLM picks whatever directory it defaults to.

**Fix:** Add to WEEBOT_CORE.md `<operating_principles>` section:

```
- Output convention: ALL generated websites and assets go under
  Output/<project-name>/. Never create project files in the workspace
  root. Use `Output/<slug>/` where slug is derived from the task description.
```

**Architecture:** System prompt (cross-cutting) — no code changes.

---

## Implementation Order

| Phase | Fixes | Files | Effort | Risk |
|-------|-------|-------|--------|------|
| **1** | Fix 1 (planner constraints) + Fix 6 (output convention) | `planner_system.txt`, `WEEBOT_CORE.md` | 15 min | Low — prompt-only |
| **2** | Fix 2 (PlanNovelty blocks) | `plan_act_flow.py`, `plan_novelty.py` | 25 min | Medium — changes flow behavior |
| **3** | Fix 3 (PowerShell boot message) | `executor.py`, `WEEBOT_CORE.md` | 15 min | Low — additive change |
| **4** | Fix 4 (step granularity) | `planner.py`, `constants.py` | 20 min | Medium — modifies plan parsing |
| **5** | Fix 5 (SVG variety) | `image_gen_tool.py` | 30 min | Medium — new template logic |

**Total:** ~1.75 hours

---

## Verification Plan

After each phase:

```bash
# Phase 1 — Planner constraints
python -m cli.main flow run "Build a website for a bakery. Single page."
# Verify: all files under Output/bakery/, index.html has embedded <style>, no external .css

# Phase 2 — PlanNovelty blocks
python -m cli.main flow run "Do something impossible: read /dev/zero and write it to /dev/null"
# Verify: after 3 identical plans, flow terminates with PlanStuckError instead of looping

# Phase 3 — PowerShell boot
python -m cli.main flow run "List all .py files in weebot/config/"
# Verify: executor uses Get-ChildItem on FIRST attempt, no ls -la errors

# Phase 4 — Step granularity
python -m cli.main flow run "Create 10 SVG icons for weather app"
# Verify: plan splits into 2 steps (5 items each), not 1 monolithic step

# Phase 5 — SVG variety
python -B -c "from weebot.tools.image_gen_tool import ImageGenTool; ..."
# Verify: two different prompts produce visually different SVGs
```

---

## Architecture Compliance Summary

| Fix | Layer | Ports Changed? | Domain Changed? | New Dependencies? |
|-----|-------|---------------|-----------------|-------------------|
| 1 | Application (prompt) | No | No | No |
| 2 | Application (flow) | No | No | `PlanStuckError` (new Application exception) |
| 3 | Application (executor) | No | No | No |
| 4 | Application (planner) | No | No | `MAX_ITEMS_PER_STEP` (new config constant) |
| 5 | Infrastructure (tool) | No | No | No — pure implementation change |
| 6 | System prompt | No | No | No |

All fixes point inward — Application depends on Domain (pure models), Infrastructure depends on Application (ports). No circular dependencies introduced.
