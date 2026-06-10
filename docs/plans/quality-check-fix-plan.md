# Implementation Plan — Quality-Check False-Negative & Related Fixes

> **Date:** 2026-06-10
> **Plan type:** Bug-fix + hardening (6 code fixes, 7 documentation fixes)
> **Architecture guardrails:** All changes respect Clean Architecture layer boundaries. No infrastructure imports introduced into application or domain.
> **Implementation status:** 2026-06-10 — Fixes 1-4 and 6-13 implemented. Fix 5 deferred (needs reproduction of DuckDuckGo CAPTCHA scenario to pinpoint stream hang root cause).

---

## Summary

A live execution trace revealed a cascade of issues: a step that succeeds (writes a 2746-char file via `file_editor`, returns structured agent output) is flagged as "empty or null-equivalent" by `StepResultValidator`, triggering redundant re-execution that wastes LLM tokens and wall-clock time. Root cause: `executing.py` never writes tool/agent output back to `Step.result`, so the validator receives `""`.

Six runtime fixes and seven documentation fixes are planned. Fixes 1-2 are the critical path; fixes 3-6 are lower-priority hardening.

---

## Fix 1 — Populate `step.result` from execution events (CRITICAL)

**Layer:** Application (Flow State)
**Files:** `weebot/application/flows/states/executing.py` lines 230-280
**Risk:** Low — purely additive, no signature changes to public APIs

### Root cause

After `context._mediator.send(ExecuteStepCommand(...))` returns events, the executing state consumes them via `reconstruct_events()` and yields them. But `step.result` on the Plan model is never updated. The domain model `Step.result` field ([`weebot/domain/models/plan.py:27`](weebot/domain/models/plan.py:27)) defaults to `None`. `Plan.update_step_status()` accepts an optional `result` parameter ([`weebot/domain/models/plan.py:107`](weebot/domain/models/plan.py:107)) but `executing.py:287` calls it without `result=`:

```python
context._plan = context._plan.update_step_status(step.id, StepStatus.COMPLETED)
```

### Fix

After the event consumption loop (`for event in reconstruct_events(...)`) and before the quality-check block, extract a textual result from the events and populate the step:

```python
# ── Extract step result from execution events for quality validation ──
_last_result_text = ""
for event in _current_step_events:
    if isinstance(event, MessageEvent) and getattr(event, 'role', '') == 'assistant':
        _last_result_text = getattr(event, 'message', '') or ""
    elif isinstance(event, ToolEvent):
        tr = getattr(event, 'result', '') or ""
        if tr and len(tr) > len(_last_result_text):
            _last_result_text = tr
if _last_result_text:
    step = step.model_copy(update={"result": _last_result_text})
```

This respects the domain model's immutability pattern (`model_copy` returns new instance; `step.model_copy(update=...)` is how `Step.mark_completed()` works at [`plan.py:35-39`](weebot/domain/models/plan.py:35-39)). The updated `step` local is then used by the validator at line 261.

**Acceptance criteria:**
- After a step produces `MessageEvent` (assistant) output, `step.result` is non-empty
- After a step produces `ToolEvent` output (e.g., `file_editor` creating a file), `step.result` is non-empty
- `StepResultValidator.validate()` is called with the extracted text, not `""`
- No regression: step with genuinely empty output still triggers quality check

**Verification:** Run `pytest tests/unit/ -k "step_result" -v` plus manual test: `python -m cli.main flow run "create a file called test.txt with content hello"` and verify no "empty or null-equivalent" warning for a successful file creation.

---

## Fix 2 — `StepResultValidator` awareness of file-creation side effects

**Layer:** Application (Service)
**Files:** `weebot/application/services/step_result_validator.py` lines 50-56
**Risk:** Low — additive parameter with default, backward-compatible

### Root cause

`StepResultValidator.validate()` checks only the `result` string parameter ([`step_result_validator.py:53-55`](weebot/application/services/step_result_validator.py:53-55)). A step that writes a 2746-char file via `file_editor` but whose `step.result` hasn't been populated (the condition Fix 1 addresses) triggers the `"" in _SUSPICIOUSLY_EMPTY` gate. But even with Fix 1, the validator should have independent awareness of persistent side effects — it's a defense-in-depth measure.

### Fix

Add an optional `step_events: list[Any] | None = None` parameter. Before the empty-result check, scan for successful file-creation tool calls:

```python
_FILE_CREATION_TOOLS = frozenset({'file_editor', 'write_file', 'create_file', 'edit_file'})

def validate(self, result: str | None, step_description: str,
             previous_result: str | None = None,
             step_events: list[Any] | None = None) -> ValidationResult:
    # If tool events show successful file creation or write, bypass empty-result check
    if step_events:
        for e in step_events:
            tn = (getattr(e, 'tool_name', '') or getattr(e, 'function_name', ''))
            if tn in _FILE_CREATION_TOOLS:
                tr = getattr(e, 'result', '') or ''
                if tr and ('Created' in str(tr) or 'Updated' in str(tr) or 'Wrote' in str(tr)):
                    return ValidationResult(passed=True)
    # ... existing logic unchanged ...
```

**Acceptance criteria:**
- `file_editor` tool with `"Created ..."` result → validator returns `passed=True` even if `result=""` 
- No change in behavior when no file-creation tools are present

**Verification:** Unit test: `test_step_result_validator_bypasses_on_file_creation()` — pass `result=""` with a `ToolEvent` showing `file_editor` `"Created /tmp/foo.md"` → expects `passed=True`.

---

## Fix 3 — Planner prompt: check local data before web search

**Layer:** Configuration (Prompt)
**Files:** `weebot/config/prompts/planner_system.txt`
**Risk:** Low — prompt change only, affects future plan generation

### Root cause

The task "show me the last 5 emails from alphasignal" produced a 7-step plan starting with web search for the newsletter's public archives, rather than checking local email data (session memory, `abook-2_contacts.json`, knowledge base). The planner system prompt lacks a directive to exhaust local resources before escalating to web retrieval.

### Fix

Add to the planner system prompt, in the planning guidelines section:

```
LOCAL-FIRST RULE: Before proposing any web search or external retrieval steps,
check whether the task can be satisfied from:
  - The user's local files (session working directory)
  - Session memory / facts already discovered
  - The knowledge base (kb_notes)
  - The user's own data (email, contacts, documents)
Only escalate to web search when local sources are exhausted or the user
explicitly asks for information not available locally.
```

**Acceptance criteria:**
- Task "show me the last 5 emails from X" proposes a step to check local email data first
- Task "what's the latest news about Y" still correctly proposes web search (local data can't answer)

**Verification:** Manual smoke test with a local-data query vs. an external-knowledge query.

---

## Fix 4 — Prioritize `web_search` tool over `bash`/curl for search queries

**Layer:** Application (Agent / Tool Registry)
**Files:** `weebot/application/agents/executor.py` tool dispatch and/or `weebot/tools/tool_registry.py`
**Risk:** Low — tool ordering change, no signature modifications

### Root cause

The agent used `bash` with `curl.exe` to hit DuckDuckGo HTML (which returned CAPTCHA challenges), then fell back to `python_execute` with `requests`+`BeautifulSoup`. The `WebSearchTool` (at `weebot/tools/web_search.py`) exists but wasn't selected. The bash-path also generates 3 SUSPICIOUS log entries per query via `bash_security.py`'s URL-chaining detection.

### Fix

In `RoleBasedToolRegistry` (or wherever the tool list is built for the executor's system prompt), ensure `web_search` appears before `bash` in the tool listing. The LLM typically picks tools in listed order for equal-applicability tasks. Additionally, in the executor system prompt (`weebot/config/prompts/executor_system.txt`), add a tool-selection rule:

```
TOOL SELECTION: For web searches and HTTP requests, always use the web_search tool.
Do NOT use bash with curl/wget for retrieving web pages — the web_search tool
handles search-engine queries and page retrieval with proper user-agent headers.
```

**Acceptance criteria:**
- Query "search for X" uses `web_search` tool, not `bash` + `curl`
- No SUSPICIOUS log entries for legitimate web search operations

**Verification:** Manual test: `python -m cli.main flow run "search for python asyncio best practices"` — check log for `web_search` tool calls vs. `bash`/curl calls.

---

## Fix 5 — Stream read timeout for HTTP responses

**Layer:** Infrastructure / Tools
**Files:** Tool handling HTTP responses — likely `weebot/tools/python_tool.py` or `weebot/tools/bash_tool.py`
**Risk:** Low — timeout addition, cannot break existing fast-completing calls

### Root cause

The execution trace ends with `"Reading web response... Reading response stream... (Number of bytes read: 0)"` — the agent is blocked on a stream read that delivered 0 bytes (likely DuckDuckGo CAPTCHA challenge returning empty body). No timeout was applied to the stream-consume phase.

### Fix

Add a deadline to the stream read. The exact location depends on which tool handles the HTTP response streaming (needs file inspection to determine — flagged for investigation). General approach:

```python
try:
    response_text = await asyncio.wait_for(
        consume_stream(response),
        timeout=10.0  # 10-second deadline for stream consumption
    )
except asyncio.TimeoutError:
    response_text = "[Error: response stream timed out after 10s]"
```

If the HTTP call goes through `bash_tool.py` → `SandboxPort`, the sandbox execution already has a timeout (300s ceiling). The issue is that the subprocess returned but the output parsing is stuck. Needs `stderr` capture + deadline on read.

**Acceptance criteria:**
- Empty/blocked HTTP responses don't hang the agent
- Error message is emitted rather than silent hang

**Verification:** Hard to reproduce (CAPTCHA-dependent). Code review + unit test with a mock that returns empty body with delayed close.

---

## Fix 6 — Rate-limit trajectory health warnings

**Layer:** Application (Agent)
**Files:** `weebot/application/agents/executor.py` lines 835-838
**Risk:** Low — logging change only, no behavioral impact

### Root cause

The trajectory health monitor's `logger.warning()` at [`executor.py:835-838`](weebot/application/agents/executor.py:835-838) is inside the per-tool-call loop (around line 821), so it fires on every tool iteration within a step. A step with 7 tool calls produces 7 identical `"Trajectory healthy for step step-1:"` warnings. This is a signal-to-noise issue — HEALTHY status should not be logged at WARNING level on every iteration.

### Fix

Change `logger.warning(...)` to `logger.debug(...)` when `diagnosis.health == TrajectoryHealth.HEALTHY`, keeping `logger.warning(...)` for non-HEALTHY states:

```python
if diagnosis.health == TrajectoryHealth.HEALTHY:
    logger.debug(
        "Trajectory %s for step %s: %s",
        diagnosis.health.value, step.id, diagnosis.detail,
    )
else:
    logger.warning(
        "Trajectory %s for step %s: %s",
        diagnosis.health.value, step.id, diagnosis.detail,
    )
```

**Acceptance criteria:**
- HEALTHY trajectory produces zero WARNING log lines
- Non-HEALTHY trajectory (STAGNATING, SEMANTIC_LOOP, TERMINAL) still produces WARNING log lines

**Verification:** Run a multi-tool step and verify `grep -c "Trajectory healthy"` on the log output.

---

## Fix 7-13 — Documentation fixes (`docs/codebase_mindmap.md`)

**Layer:** Documentation
**Files:** `docs/codebase_mindmap.md`
**Risk:** None (documentation-only)

### Fix 7 — Add missing Mermaid edges (§3)

Add the following edges to the Mermaid diagram:
```
Agents --> AppModels        %% ExecutorAgent depends on PlanActFlowConfig
MCP --> Tools               %% MCP server wraps tool classes directly
WebRouters --> Flows        %% Web routers call flows, not just factories
CLI --> Flows               %% AgentRunner calls flows directly
Flows --> HookPort          %% PlanActFlowConfig.hooks consumes HookRegistryPort
```

### Fix 8 — Remove `PlanActFlowConfig` from Entity Map (§6)

`PlanActFlowConfig` is a configuration `@dataclass`, not a domain entity. The Entity Map is for persisted/passed data entities. Remove the row or add an explicit note: "Included for completeness; this is a configuration object, not a data entity."

### Fix 9 — Add quality-check bug to Risk Register (§7)

Insert into the Risk Register table:

| Risk | Severity | Location | Evidence |
|------|----------|----------|----------|
| `Step.result` never populated from tool/agent output after CQRS mediator execution — `StepResultValidator` receives `""` and false-negatives on completed steps, triggering redundant re-execution | **MEDIUM** | `executing.py:260-264`, `step_result_validator.py:55` | Runtime log: step wrote 2746-char file via `file_editor` + returned structured agent output, but quality gate flagged `"empty or null-equivalent"` and retried with hint |

### Fix 10 — Add quality-check gate to Data Flow Path 1 (§4)

Insert between `PlanActFlow._emit()` and the final event yield:
```
→ ExecutingState quality gate [executing.py:260-280] → StepResultValidator.validate()
→ [on fail] inject quality hint → retry (stay in ExecutingState)
→ [on pass] → update_step_status(COMPLETED)
```

### Fix 11 — Mark service list truncation (§2)

In the Services section, after the enumerated ~65 services, add: `[... 6 additional service files — see full glob for complete inventory]`.

### Fix 12 — Weaken self-validation claim (footer)

Replace the terminal claim:
> *"Every claim in sections 1-7 traceable to specific file:line citations..."*

With:
> *"All factual claims in sections 1-7 are traceable to file:line citations verified during 2026-06-10 traversal. The Mermaid diagram is a structural synthesis — individual edges were not exhaustively import-traced. Section 8 logs remaining uncertainties including 6 unverified or partially-surveyed module areas."*

### Fix 13 — Document trajectory-healthy noise (§4 or §7)

Add to Data Flow Path 1, Failure Modes: *"Trajectory health monitor fires on every tool call within a step, producing repeated `WARNING` log lines (observed: 7 identical messages for one step). HEALTHY state logged at WARNING severity — reduced signal-to-noise ratio in production logs."*

---

## Layer-impact summary

| Fix | Layer | Files touched | Dependency direction |
|-----|-------|--------------|---------------------|
| 1 | Application (Flow State) | `executing.py` | Domain → Application ✓ |
| 2 | Application (Service) | `step_result_validator.py` | Domain → Application ✓ |
| 3 | Config (Prompt) | `planner_system.txt` | No code deps |
| 4 | Application (Agent) | `executor.py`, `executor_system.txt` | Domain → Application ✓ |
| 5 | Infrastructure/Tools | `python_tool.py` or `bash_tool.py` | Ports → Infrastructure ✓ |
| 6 | Application (Agent) | `executor.py:835-838` | Domain → Application ✓ |
| 7-13 | Documentation | `codebase_mindmap.md` | No code deps |

No fix introduces a cross-layer violation. All application-layer changes depend on domain models (permitted inward direction). Fix 5 requires file inspection before determining exact target.

---

## Execution order

1. **Fixes 1 + 2 together** ✅ — `executing.py` + `step_result_validator.py`
2. **Fix 3** ✅ — `planner_system.txt`
3. **Fix 4** ✅ — `executor_system.txt`
4. **Fix 6** ✅ — `executor.py` trajectory health log level
5. **Fixes 7-13** ✅ — `docs/codebase_mindmap.md`
6. **Fix 5** ⏳ DEFERRED — Stream read timeout for HTTP responses. The "Reading web response... (0 bytes)" text originates from agent-generated Python code (within `python -c` subprocess), not weebot source. Requires reproduction of the specific DuckDuckGo CAPTCHA scenario to determine if the bash_tool's 60s timeout ceiling is insufficient or if the subprocess output pipe hangs. Suggested approach: (a) replicate the curl command, (b) check if `SandboxPort.execute()` deadline propagates to subprocess stdout pipe reads, (c) add a pipe-read deadline if needed.

---

## Rollback plan

- **Fixes 1-2:** The `step.result` population is additive — if it causes issues, revert the extraction block. The validator's `step_events` parameter is optional with default `None` — removing the caller's argument restores prior behavior.
- **Fix 3:** Revert the prompt file to prior version.
- **Fix 4:** Revert tool list ordering and prompt line.
- **Fix 5:** Remove the `asyncio.wait_for` wrapper.
- **Fix 6:** Change `logger.debug` back to `logger.warning` for HEALTHY.
- **Fixes 7-13:** `git checkout -- docs/codebase_mindmap.md` (documentation has no runtime effect).
