# Implementation Plan — Runtime Trace Bug Fixes

> **Date:** 2026-06-10
> **Plan type:** Bug-fix (2 code fixes, 1 prompt fix)
> **Evidence:** Live session trace `weebot01` (audit task, steps 1-2)
> **Architecture guardrails:** All changes respect layer boundaries. Config → Tools → Application.

---

## Summary

A live execution trace from session `weebot01` (auditing architecture adherence) surfaced three distinct issues:

1. **bash_tool timeout cascade** — Agent defaults to 30-60s timeout for recursive filesystem operations across 123K files, causing timeout + retry waste (step 1 consumed 166s, 10+ bash calls)
2. **nl_cron.py `parse_schedule("once")` returns `None`** — "once" is a valid schedule type (DateTrigger) but the NL parser silently returns `None`, risking `TypeError` in callers
3. **Command-blocked error format** — `ExecApprovalPolicy` blocks commands containing `kill` text; agent falls back correctly but error message format could confuse the agent about what went wrong

---

## Fix 1 — Add filesystem-operation timeout guidance to executor prompt

**Layer:** Config (Prompt)
**File:** `weebot/config/prompts/executor_system.txt`
**Risk:** Low — prompt-only change, affects future tool selection

### Root cause

The agent issued recursive `Get-ChildItem -Recurse` across 123,748 items with a default 60s timeout. This timed out (obvious in hindsight — 123K IO operations). The agent retried with 300s then ran 8 paginated reads to recover. Total step time: 166s when ~5s of tool runtime would have sufficed with appropriate timeout upfront.

### Fix

Add a `<bash_timeouts>` section to the `<tool_selection_rules>` or `<bash_rules>` block in `executor_system.txt`:

```
<bash_timeout_guidance>
- Filesystem listing operations (Get-ChildItem -Recurse, dir /s, ls -R,
  find . -type f, tree) on directories larger than ~100 items need
  timeout >= 300s. The default 30s will time out.
- For controlled output, prefer explicit depth limits:
  Get-ChildItem -Path "..." -Recurse -Depth 3  instead of unrestricted.
- When reading large files, use pagination from the start:
  Get-Content "...large_file.txt" | Select-Object -First 200
  rather than loading the whole file first.
- If a command times out, DO NOT retry with the same command and longer
  timeout — change the strategy (add -Depth, add -First, or switch to
  a lighter tool).
</bash_timeout_guidance>
```

### Verification

Manual test: `python -m cli.main flow run "list all files in E:\Documents\Vibe-Coding\weebot"` → verify the agent uses `-Depth` limit or sets timeout ≥ 120s upfront, no timeout-then-retry pattern.

---

## Fix 2 — `nl_cron.py` — Add "once" / single-execution schedule parsing

**Layer:** Infrastructure (Scheduling)
**File:** `weebot/scheduling/nl_cron.py`
**Risk:** Low — additive, returns a valid dict instead of `None`

### Root cause

`parse_schedule("once")` returns `None` because "once" doesn't map to any cron pattern. But `SchedulingManager` (`weebot/scheduling/scheduler.py`) supports `DateTrigger` and `"once"` trigger type — the scheduling infrastructure CAN handle one-shot jobs, but the NL parser doesn't recognize the input. Callers that unpack `parse_schedule()` assume a dict return and would hit `TypeError` on `None`.

**Evidence:** `parse_schedule("once")` → `None` (verified by runtime test). `SchedulingManager.create_job()` at `scheduler.py` accepts `trigger_type: TriggerType` which includes `TriggerType.ONCE = "once"`.

### Fix

Add a handling block at the top of `parse_schedule()` that matches "once", "once now", "run once", "immediately" patterns:

```python
def parse_schedule(text: str) -> dict | None:
    """Parse natural language schedule into a cron dict.
    
    Returns:
        dict with ``cron_expression`` and ``description`` keys,
        or ``{"trigger_type": "once", "description": "..."}`` for one-shot.
        Returns ``None`` when no pattern is recognized.
    """
    text = text.strip().lower()
    
    # One-shot / immediate execution
    if text in ("once", "once now", "run once", "immediately", "now"):
        return {
            "trigger_type": "once",
            "description": "Run once immediately",
        }
    
    # ... existing logic ...
```

Callers (`SchedulingManager.create_job()`) that check `trigger_config.get("trigger_type") == "once"` already handle this — no consumer changes needed.

### Verification

```python
>>> from weebot.scheduling.nl_cron import parse_schedule
>>> parse_schedule("once")
{'trigger_type': 'once', 'description': 'Run once immediately'}
>>> parse_schedule("now")
{'trigger_type': 'once', 'description': 'Run once immediately'}
```

---

## Fix 3 — Improve Command-blocked error message clarity

**Layer:** Tools (bash_tool)
**File:** `weebot/tools/bash_tool.py:379-384`
**Risk:** Low — message text change only

### Root cause

When `ExecApprovalPolicy` blocks a command, the error message is:
```
Command blocked — requires user confirmation: Save PID/name before killing.
```

The `undo_hint` text ("Save PID/name before killing") is a security instruction meant for the approval UI, not an explanation of WHY the command was blocked. When injected into the agent's tool result error, it's confusing — the agent may interpret it as "I need to save a PID and kill something" and retry with different syntax.

### Fix

Add a separate user-facing reason to the `ToolResult.error` field that explains the blocking category rather than the undo hint:

```python
if approval.requires_confirmation:
    category = getattr(approval, 'category', 'security policy')
    return ToolResult(
        output="",
        error=(
            f"Command blocked by {category}: {approval.reason}. "
            f"Find an alternative approach that does not trigger this policy."
        ),
    )
```

The current code at line 375 uses `approval.reason` which already contains the policy reason. Let me check what that string looks like.

### Verification

Trace already shows the agent successfully falling back to `file_editor` after the block. New error message should make the reason clearer so the agent picks the right fallback faster.

---

## Non-actionable — Semantic loop on step-2 is working as designed

**Symptom:** `WARNING [executor] Trajectory semantic_loop for step step-2: Different tool calls producing identical output`

**Finding:** This is NOT a bug. The `TrajectoryMonitor` at `trajectory_monitor.py:119-130` correctly detected 3 consecutive tool calls producing identical output hashes. It injected a recovery message ("Try a completely different search strategy") into the conversation buffer at `executor.py:831-833`. The step then completed in 110s — the recovery message worked and the agent adapted.

The `SEMANTIC_LOOP` auto-abort at `executor.py:849-856` fires if the agent ignores the recovery message and continues producing identical outputs, which would then produce a `WaitForUserEvent`. This is correct defensive behavior.

**No code change needed.** The trajectory health fix from earlier (HEALTHY → DEBUG) correctly demotes noisy HEALTHY logs while keeping SEMANTIC_LOOP at WARNING.

---

## Execution order

1. **Fix 2** — `nl_cron.py` — Simple, independent, tests itself
2. **Fix 1** — `executor_system.txt` — Prompt change, no code coupling
3. **Fix 3** — `bash_tool.py:379` — Message text change, independent

All three fixes are independent — no ordering constraints.

---

## Layer-impact summary

| Fix | Layer | Dependency direction | Lines |
|-----|-------|---------------------|-------|
| `nl_cron.py` — "once" handling | Infrastructure (Scheduling) | No code deps | +5 |
| `executor_system.txt` — timeout guidance | Config (Prompt) | No code deps | +12 |
| `bash_tool.py` — block error clarity | Tools | `core/approval_policy` → Tools ✓ | ~3 |

No cross-layer violations. All changes are within-layer.

---

## Rollback

- `git checkout -- weebot/scheduling/nl_cron.py`
- `git checkout -- weebot/config/prompts/executor_system.txt`
- `git checkout -- weebot/tools/bash_tool.py`

Each file change is self-contained. No migration or schema changes.
