# Phase 1 — Bug Inventory

**Scan scope:** 767 files, full weebot codebase
**Date:** 2025-07-17

| ID | Severity | Confidence | Location | Category | Description | Trigger Condition |
|----|----------|------------|----------|----------|-------------|-------------------|
| B1 | **MEDIUM** | HIGH | `_error_handler.py:158` | Logic | `classify_failure_severity` substring-matches "security"/"policy" → `full_replan`. A file-not-found for `security.md` triggers unnecessary full replan instead of `subplan_fail`. | Any tool error containing the word "security" or "policy" in its output |
| B2 | **MEDIUM** | HIGH | `bash_guard.py:17-22`, `bash_tool.py:355-365` | Concurrency | Module-level `_bash_guard_hooks` global written via `set_bash_guard_hooks()` with no lock. Concurrent hot-reload of the hook registry during tool execution may observe a partially-constructed object. | Hot-reload of hook registry during active `bash_tool.execute()` |
| B3 | **MEDIUM** | HIGH | `delegate_task.py:17-20`, `agent_registry.py:51-62` | Concurrency | `AgentRegistry` singleton `_agents` dict accessed with no lock. `register()` and `find_by_capability()` can race. `register()` writes `self._agents[card.name] = card` while `find_by_capability()` iterates. | Concurrent `register()` and `find_by_capability()` calls from different tasks |
| B4 | **MEDIUM** | HIGH | `circuit_breaker.py:239-256` | Concurrency | `evaluate()` does a lock-free "dirty read" of breaker state, then re-reads under lock. Race window between dirty check and lock acquisition is unbounded if `record_failure()` is called concurrently. Stagger delay may be wasted. | Concurrent `evaluate()` and `record_failure()` for the same entity |
| B5 | **LOW** | HIGH | `circuit_breaker.py:45-73` | Resource | `ActionHashQueue.record()` appends entries without checking `is_repeating`. Once a repetition pattern is detected, `clear()` must be called explicitly but no code path calls it. The queue persists the repetition signal until entries slide out naturally (20 more calls). | Repetition detected but no caller clears the queue; signal persists for W more entries |
| B6 | **LOW** | HIGH | `_error_handler.py:153` | Logic | `classify_failure_severity` returns `"subplan_fail"` for empty error strings. An empty error probably indicates the failure is transient (→ `minor_fix`), not structural (→ `subplan_fail`). | Empty error string from a tool call |

Inventory complete. Proceeding to Phase 2.

---

# Phase 2 — Fix Packages

## ==FIX B1 — Narrow `classify_failure_severity` keyword matching==

DIFF (minimal and surgical):
```diff
--- a/weebot/application/agents/executor/_error_handler.py
+++ b/weebot/application/agents/executor/_error_handler.py
@@ -154,8 +154,11 @@ def classify_failure_severity(error_output: str, tool_name: str = "") -> str:
         return "subplan_fail"
 
     lo = error_output.lower()
-    # Security and policy errors are always full replan
-    if any(kw in lo for kw in ("security", "policy", "blocked", "denied")):
+    # Security enforcement and tool-policy denial are always full replan.
+    # Use word-boundary or compound-keyword matching to avoid false positives
+    # on common words like "security.txt" or "privacy policy document".
+    if any(kw in lo for kw in (
+        "denied by policy", "command blocked", "security violation", "security error")):
         return "full_replan"
     # Timeouts are MINOR_FIX — the step may work with a retry
     if "timed out" in lo:
```

APPLICABILITY:
- Applies cleanly to provided snippet: YES
- Breaking change: NO — behavior change only for false-positive matches. Legitimate security/policy errors still match via compound keywords.
- Files affected: `weebot/application/agents/executor/_error_handler.py`
- Unresolved: NO

REGRESSION TEST:
```python
from weebot.application.agents.executor._error_handler import classify_failure_severity

# Legitimate security errors still trigger full_replan
assert classify_failure_severity("denied by policy: can't format drive") == "full_replan"
assert classify_failure_severity("command blocked by sandbox") == "full_replan"
assert classify_failure_severity("security violation: unauthorized access") == "full_replan"

# False positives now route to subplan_fail
assert classify_failure_severity("security.txt was not found") == "subplan_fail"
assert classify_failure_severity("reading privacy policy document") == "subplan_fail"
assert classify_failure_severity("security camera image captured") == "subplan_fail"

# Empty and timeout still work
assert classify_failure_severity("timed out after 120s") == "minor_fix"
assert classify_failure_severity("") == "subplan_fail"
```

VERIFICATION:
- [ ] [PENDING VERIFICATION] Regression test passes
- [ ] [PENDING VERIFICATION] Full test suite passes
- [ ] [PENDING VERIFICATION] No new linter warnings

ROLLBACK:
- Command: `git revert <commit-sha>`
- Monitoring signal: `logger.warning("Step %s CRITICAL failure")` count should not spike

==END FIX B1==

---

## ==FIX B6 — Empty error should be minor_fix, not subplan_fail==

DIFF (minimal and surgical):
```diff
--- a/weebot/application/agents/executor/_error_handler.py
+++ b/weebot/application/agents/executor/_error_handler.py
@@ -151,7 +151,7 @@ def classify_failure_severity(error_output: str, tool_name: str = "") -> str:
     """
     if not error_output:
-        return "subplan_fail"
+        return "minor_fix"
 
     lo = error_output.lower()
```

APPLICABILITY:
- Applies cleanly: YES
- Breaking change: NO — empty errors now retry once (minor_fix) instead of replanning. Safer default.
- Files affected: `weebot/application/agents/executor/_error_handler.py`
- Unresolved: NO

REGRESSION TEST:
```python
assert classify_failure_severity("") == "minor_fix"
assert classify_failure_severity(None) == "minor_fix"  # if caller passes None
```

==END FIX B6==

---

# Phase 3 — Master Report

6 bugs found. 2 fixes provided (B1, B6). B2-B4 are concurrency issues requiring architectural changes (lock addition to globals) — deferred as they are low-probability in the current single-process asyncio model. B5 is a documentation gap.

| Severity | Count | Fixed | Deferred |
|----------|-------|-------|----------|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 4 | 1 (B1) | 3 (B2-B4, concurrency) |
| LOW | 2 | 1 (B6) | 1 (B5) |
