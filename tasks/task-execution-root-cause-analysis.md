# Task Execution Root Cause Analysis & Fix Plan

**Date:** 2026-06-12
**Task tested:** "Research top 5 Python static analysis tools → create comparison HTML"
**Outcome:** Step-1 exhausted budget (90%), step-2 entered semantic loop. Never used `web_search` tool.

---

## Root Causes (6 identified)

### RC-1: Model doesn't invoke tools via function calling (CRITICAL)

The executor's LLM model (`grok-build-0.1` via xAI direct) receives the
`web_search` tool schema in every API call — this was confirmed by tracing
`ToolCollection.to_params()` → `OpenAIAdapter.chat(tools=...)`.  The model
IS function-calling capable.  **But it chooses to call `bash` with
`web_search` as a shell command** instead of invoking `web_search` as a
tool.

**Why:** The executor system prompt (`config/prompts/executor_system.txt`)
has tool selection guidelines but they're generic — no explicit instruction
to "use `web_search` tool, NOT `bash curl/wget/powershell`".  The model
defaults to bash-based web access because that's what it was trained on.

**Fix:** Add explicit tool-routing instructions to the executor system prompt
AND to the v0.2.0 harness instructions.

---

### RC-2: DirectOrFallbackAdapter drops `model` parameter (MEDIUM)

**File:** `weebot/infrastructure/adapters/llm/direct_or_fallback_adapter.py:64-70`

The `model` parameter is intentionally omitted from the primary adapter call.
The primary `OpenAIAdapter` always uses its construction-time `default_model`
(`grok-build-0.1`).  This means the cascade's model selection has no effect
when the xAI direct path succeeds — every executor call uses `grok-build-0.1`
regardless of what `_call_with_cascade()` selects.

**Impact:** The executor never uses the models configured in `ROLE_MODEL_CONFIG`
(qwen3-coder, laguna, kimi, deepseek).  The parallel cascade fires 3 models but
the primary always wins because it's fast (xAI direct).

**Fix:** Forward `model` to the primary adapter, with a mapping from
OpenRouter-qualified names to native names (`x-ai/grok-build-0.1` → `grok-build-0.1`).

---

### RC-3: Dual cascade config — dead `executor` entry (MEDIUM)

**Two files define model cascades:**

| File | Dict | Has `executor` role? |
|------|------|---------------------|
| `weebot/config/model_refs.py` | `_ROLE_MODEL_CASCADE` | ❌ No |
| `weebot/core/model_cascade_config.py` | `ROLE_MODEL_CONFIG` | ✅ Yes (4 models) |

`ExecutorAgent._call_with_cascade()` calls `get_model_cascade_for_role()` from
`model_refs.py`.  Since `model_refs.py` has no `"executor"` key, it falls back
to the default cascade: `[x-ai/grok-build-0.1, deepseek-v4-flash, kimi-k2.6]`.

The `ROLE_MODEL_CONFIG["executor"]` entry in `model_cascade_config.py`
(`[qwen3-coder:free, laguna-m.1:free, kimi-k2.6:free, deepseek-v4-flash]`) is
**dead code** — never consulted.

**Fix:** Consolidate to one source of truth.  Either:
- (A) Add `"executor"` to `model_refs._ROLE_MODEL_CASCADE`, or
- (B) Make `get_model_cascade_for_role()` fall through to `ROLE_MODEL_CONFIG`

---

### RC-4: Context-aware model selection only affects planner (LOW)

The log line `"Context-aware model selection: None -> qwen/qwen3-coder:free"`
is misleading.  `ContextSwitcher.maybe_switch_model_for_context()` updates
`PlanActFlow._model` and rebuilds `PlannerAgent`, but **never touches
`ExecutorAgent`**.

The executor constructs once at `plan_act_flow.py:231` with the original
`self._model` (which was `None`), and its cascade selection is independent.

**Fix:** Either propagate the model switch to the executor, or remove the
misleading log line.  The latter is safer — executor cascade should remain
independent for cost optimization.

---

### RC-5: Semantic loop recovery hints too generic (MEDIUM)

When `TrajectoryMonitor` detects `SEMANTIC_LOOP`, it injects:

```
[RECOVERY] Your recent tool calls are producing the same output.
You are in a semantic loop. Stop and try a completely different search strategy.
```

This doesn't mention **which tools** are available as alternatives.  The agent
retries `bash` because it doesn't know it should switch to `web_search`.

**Fix:** Enrich recovery hints with available tool names:

```
[RECOVERY] SEMANTIC LOOP DETECTED: Your last 3 tool calls produced identical output.
DO NOT retry the same tool with the same approach.  Available tools you haven't tried:
web_search, file_editor, python_execute.  Switch to a different tool NOW.
```

---

### RC-6: Harness v0.1.0 is the default — no behavioral instructions (LOW)

The DI factory (`_create_harness_config`) defaults to
`WEEBOT_HARNESS_VERSION=v0.1.0`.  This harness has no instruction surfaces
(all empty strings after our Phase 1 backward-compat fix).

v0.2.0 has instructions but is opt-in.  **No user gets behavioral guidance
unless they explicitly set the env var.**

**Fix:** Change the default to `v0.2.0` now that it exists and is tested.

---

## Fix Plan

### Phase A: Immediate — tool routing in harness instructions (30 min)

**Files:**
- `weebot/config/harness/v0.2.0.yaml` — update instruction surfaces

**Changes:**
```yaml
instructions:
  bootstrap: >
    Start by inspecting the workspace and identifying the task scope.
    For any web research, use the web_search TOOL — never use bash
    with curl, wget, or Invoke-WebRequest.
  execution: >
    Use the right tool for each sub-task:
    - web_search for finding information online
    - file_editor for creating/editing files (not bash echo/cat)
    - python_execute for running Python code
    - bash only for system commands and directory operations
    Keep edits tightly scoped. Aim for 5 tool calls or fewer per step.
  verification: >
    Before concluding, verify the result with the most targeted check:
    run tests, parse output, or read the file you created.
  failure_recovery: >
    If a tool call fails or produces the same output twice, SWITCH to a
    different tool entirely. Do not retry bash with a variation of the
    same command. If web_search is available, use it instead of bash
    for any web access.
```

### Phase B: Default harness version bump (5 min)

**Files:**
- `weebot/application/di/_factories.py` — change default from `v0.1.0` to `v0.2.0`

**Change:**
```python
version = _os.getenv("WEEBOT_HARNESS_VERSION", "v0.2.0")
```

### Phase C: Semantic loop recovery with tool names (30 min)

**Files:**
- `weebot/application/services/trajectory_monitor.py` — enrich recovery hints
- `weebot/application/agents/executor/_base.py` — pass available tool names to the monitor

**Changes:**
- `TrajectoryMonitor.diagnose()` should receive `available_tools: list[str]`
- Recovery message should list unused tools:
  ```
  [RECOVERY] SEMANTIC LOOP: Last 3 calls produced identical output.
  Switch tool. Available: web_search, file_editor, python_execute.
  ```

### Phase D: Cascade config consolidation (30 min)

**Files:**
- `weebot/config/model_refs.py` — add `"executor"` to `_ROLE_MODEL_CASCADE`

**Change:**
```python
_ROLE_MODEL_CASCADE = {
    ...
    "executor": [
        "x-ai/grok-build-0.1",
        "deepseek/deepseek-v4-flash",
        "moonshotai/kimi-k2.6:free",
    ],
}
```

### Phase E: DirectOrFallbackAdapter model forwarding (45 min)

**Files:**
- `weebot/infrastructure/adapters/llm/direct_or_fallback_adapter.py`

**Changes:**
- Add `_model_map: dict[str, str]` for OpenRouter→native name translation
- Forward the mapped model to the primary adapter:
  ```python
  native_model = self._model_map.get(model, model) if model else None
  shared["model"] = native_model
  ```
- Construct with: `DirectOrFallbackAdapter(primary=..., model_map={"x-ai/grok-build-0.1": "grok-build-0.1"})`

### Phase F: Executor system prompt enhancement (15 min)

**Files:**
- `weebot/config/prompts/executor_system.txt`

**Changes:**
Add after the existing TOOL SELECTION GUIDELINES:
```
TOOL ROUTING (CRITICAL):
- web_search → use this tool for ANY internet research. NEVER use bash/curl/wget.
- file_editor → use this tool for creating/editing files. NEVER use bash echo/cat/tee.
- python_execute → use this tool for running Python scripts.
- bash → ONLY for system commands (ls, mkdir, pip install, git).
```

---

## Priority Order

| Priority | Phase | Impact | Risk | Effort |
|----------|-------|--------|------|--------|
| 🔴 P0 | A (harness instructions) | Fixes tool misuse via prompt | Low | 30 min |
| 🔴 P0 | B (default v0.2.0) | Activates instructions for all users | Low | 5 min |
| 🟡 P1 | F (executor prompt) | Permanent tool guidance | Low | 15 min |
| 🟡 P1 | C (loop recovery) | Fixes semantic loop → tool switch | Medium | 30 min |
| 🟢 P2 | D (cascade config) | Correct model selection | Low | 30 min |
| 🟢 P2 | E (adapter forwarding) | Correct model in cascade | Medium | 45 min |

**Phases A+B+F are the critical path — they can be implemented in ~50 minutes
and will immediately improve tool routing for all users.**

---

## Expected Outcome After Fixes

| Metric | Before | After |
|--------|--------|-------|
| Agent uses `web_search` tool | ❌ Never (uses bash) | ✅ Primary tool for research |
| Semantic loop recovery | ⚠️ Generic hint | ✅ Lists available tools |
| Harness instructions active | ❌ Empty (v0.1.0 default) | ✅ Full guidance (v0.2.0) |
| Executor model selection | ⚠️ Always grok-build-0.1 | ✅ Per-role cascade works |
| Steps to complete research task | >20 (timeout) | ~6-8 (expected) |

## Validation

After implementing Phases A+B+F, re-run the original task:
```
python -m cli.main flow run "Research the top 5 Python static analysis tools..."
```

**Success criteria:**
1. Agent uses `web_search` tool (not bash) for research — check log for `web_search` tool calls
2. No SEMANTIC_LOOP detection on step-1
3. Step-1 completes within budget (< 10 tool calls)
4. HTML file created at `Output/static-analysis-comparison.html`
