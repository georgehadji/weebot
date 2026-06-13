# Execution Fixes Plan
**Scope**: Fix all bugs and failure patterns observed in the weebot execution log (June 2026)  
**Architecture constraint**: Every fix must respect the Dependency Rule — Domain ← Application ← Infrastructure ← Interfaces. No outer-layer imports into inner layers.

---

## Root Cause Summary

The execution log reveals a compound failure chain:

1. `security_validators.py` fires false-positive blocks on benign paths and PowerShell commands
2. Those identical error strings saturate the trajectory monitor's SEMANTIC_LOOP detector
3. The code reviewer only sees the last 10 tool events (max_events=10), misses the actual file writes, and issues wrong REVISE verdicts
4. Wrong REVISE causes the executor to re-run completed steps 4+ times until the plan fingerprint similarity guard fires
5. Generated output code in `Output/windows-autonomous-agent/` has 4 logic bugs that would fail pytest even after the framework issues are fixed

---

## Fix Index

| # | Category | File | Priority |
|---|----------|------|----------|
| 1 | Security allowlist too narrow | `infrastructure/security/security_validators.py:55` | HIGH |
| 2 | `CommandValidator` blocks common stdlib imports | `infrastructure/security/security_validators.py:329` | HIGH |
| 3 | `bypass` pattern too broad in PowerShell validator | `infrastructure/security/security_validators.py:248` | HIGH |
| 4 | Bash `$()` pattern fires on PowerShell code | `infrastructure/security/security_validators.py:259` | MEDIUM |
| 5 | Code reviewer truncates to last 10 tool events | `application/services/code_reviewer_service.py` | HIGH |
| 6 | Code reviewer bare `except Exception` silently approves on parse error | `application/services/code_reviewer_service.py` | MEDIUM |
| 7 | Static `undo_hint` in `python_tool.py` misleads agent | `tools/python_tool.py` | MEDIUM |
| 8 | Trajectory abort message hides security cascade context | `application/agents/executor.py:850` | LOW |
| 9 | Generated output bug: `get_current_step()` returns list not item | `Output/windows-autonomous-agent/src/domain/models.py` | HIGH |
| 10 | Generated output bug: `in_progress` assignment incomplete | `Output/windows-autonomous-agent/src/domain/agent.py` | HIGH |
| 11 | Generated output bug: wrong import path in test file | `Output/windows-autonomous-agent/tests/test_domain.py` | HIGH |
| 12 | Generated output bug: plan status never transitions DRAFT→IN_PROGRESS | `Output/windows-autonomous-agent/src/domain/models.py` | HIGH |

---

## Fix 1 — Extend PathValidator.ALLOWED_EXTENSIONS

### Problem
`PathValidator.ALLOWED_EXTENSIONS` at `weebot/infrastructure/security/security_validators.py:55-60` does not include `.example`, `.env`, `.toml`, `.lock`, `.gitignore`, `.editorconfig`, `.gitkeep`, `.dockerignore`, and similar scaffolding files. When the agent tries to create `.env.example` or `Cargo.lock`, `file_editor` returns a validation error:

```
File extension not allowed: .example
```

This triggers the policy-error-loop detector in the executor (3 consecutive `security_blocked` errors → `WaitForUserEvent`), collapsing the step.

### Layer
`Infrastructure` — `PathValidator` lives in `weebot/infrastructure/security/security_validators.py`. The change is contained to that layer; no inner layer is touched.

### Fix
```python
# weebot/infrastructure/security/security_validators.py

ALLOWED_EXTENSIONS: set[str] = {
    # Source and config
    ".txt", ".md", ".py", ".pyi", ".json", ".yaml", ".yml",
    ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".xml", ".csv",
    ".log", ".ini", ".cfg", ".conf", ".sql", ".sh",
    ".ps1", ".bat", ".cmd",
    # New: scaffolding and tooling files
    ".toml", ".lock", ".env", ".example",
    ".gitignore", ".gitkeep", ".gitattributes",
    ".dockerignore", ".editorconfig",
    ".prettierrc", ".eslintrc",
    ".flake8", ".mypy", ".pylintrc",
    ".nvmrc", ".node-version",
    ".rst", ".tex",       # documentation
    ".tf", ".tfvars",     # Terraform
    ".Makefile",          # no extension but kept for awareness
}
```

Note: `.env` contains real secrets when populated, but blocking *creation* of an empty `.env` file prevents the agent from scaffolding projects. The security guarantee is from the bash guard and credential sanitizer at write time, not from blocking the file extension.

### Test
```python
# tests/unit/test_security_validators.py
def test_path_validator_allows_env_example(tmp_path):
    v = PathValidator(workspace_root=tmp_path)
    path = tmp_path / ".env.example"
    report = v.validate(path, allow_create=True)
    assert report.result == ValidationResult.VALID

def test_path_validator_allows_toml(tmp_path):
    v = PathValidator(workspace_root=tmp_path)
    path = tmp_path / "pyproject.toml"
    report = v.validate(path)
    assert report.result == ValidationResult.VALID
```

---

## Fix 2 — Downgrade stdlib imports from BLOCK to CONFIRM in CommandValidator

### Problem
`CommandValidator.validate_python` at `weebot/infrastructure/security/security_validators.py:329` returns `DANGEROUS_PATTERN` for any Python code that imports `sys`, `builtins`, `mmap`, or `ctypes`. This is correct for truly dangerous patterns but too aggressive for `sys` — virtually every script uses `sys.argv` or `sys.path`. The blanket block causes the `python_execute` tool to reject standard test runners and setup scripts.

```python
dangerous_imports = {'socket', 'ctypes', 'mmap', 'sys', 'builtins'}
```

### Layer
`Infrastructure` — same file as Fix 1.

### Fix

Split the set into two tiers: modules that should be outright blocked vs. modules that require user confirmation but should not abort the request:

```python
# weebot/infrastructure/security/security_validators.py

# Imports that are always dangerous — return DANGEROUS_PATTERN
_BLOCKED_IMPORTS: set[str] = {'ctypes', 'mmap', 'builtins'}

# Imports that are elevated risk but commonly legitimate — require confirmation
_CONFIRM_IMPORTS: set[str] = {'socket', 'sys'}

def validate_python(self, code: str) -> ValidationReport:
    """Validate Python code for dangerous patterns."""
    for pattern in self.PYTHON_DANGEROUS:
        if pattern.search(code):
            return ValidationReport(
                result=ValidationResult.DANGEROUS_PATTERN,
                message="Dangerous Python pattern detected",
                matched_pattern=pattern.pattern,
            )

    import_pattern = re.compile(
        r'^\s*import\s+(\w+)|^\s*from\s+(\w+)\s+import', re.MULTILINE
    )
    for match in import_pattern.finditer(code):
        module = match.group(1) or match.group(2)
        if module in _BLOCKED_IMPORTS:
            return ValidationReport(
                result=ValidationResult.DANGEROUS_PATTERN,
                message=f"Import of '{module}' is not allowed",
                matched_pattern=f"import {module}",
            )
        if module in _CONFIRM_IMPORTS:
            return ValidationReport(
                result=ValidationResult.DANGEROUS_PATTERN,
                message=f"Import of '{module}' requires confirmation",
                matched_pattern=f"import {module}",
            )

    return ValidationReport(
        result=ValidationResult.VALID,
        message="Python code is valid",
    )
```

### Test
```python
def test_sys_import_raises_confirmation_not_block():
    v = CommandValidator()
    report = v.validate_python("import sys\nprint(sys.argv)")
    assert report.result == ValidationResult.DANGEROUS_PATTERN
    assert "confirmation" in report.message.lower()

def test_ctypes_import_is_blocked():
    v = CommandValidator()
    report = v.validate_python("import ctypes")
    assert report.result == ValidationResult.DANGEROUS_PATTERN
    assert "not allowed" in report.message.lower()
```

---

## Fix 3 — Narrow the `bypass` pattern in PowerShell validator

### Problem
`CommandValidator.POWERSHELL_DANGEROUS` at `security_validators.py:248` includes:

```python
re.compile(r'bypass', re.IGNORECASE),
```

This matches the word "bypass" *anywhere* in the command, including variable names like `bypass_validation`, parameter descriptions, or even comment strings. The false-positive fires on completely benign PowerShell scripts that happen to contain the word, producing a `DANGEROUS_PATTERN` error that blocks the step.

### Layer
`Infrastructure` — same file.

### Fix
Replace the broad `bypass` pattern with one that specifically targets PowerShell execution policy bypass:

```python
# weebot/infrastructure/security/security_validators.py
# BEFORE:
re.compile(r'bypass', re.IGNORECASE),

# AFTER (replace with two precise patterns):
re.compile(r'-ExecutionPolicy\s+Bypass', re.IGNORECASE),
re.compile(r'-ep\s+bypass', re.IGNORECASE),
```

### Test
```python
def test_execution_policy_bypass_blocked():
    v = CommandValidator()
    r = v.validate_powershell("powershell -ExecutionPolicy Bypass -File script.ps1")
    assert r.result == ValidationResult.DANGEROUS_PATTERN

def test_bypass_in_variable_name_not_blocked():
    v = CommandValidator()
    r = v.validate_powershell("$bypass_check = $false; Write-Output 'done'")
    assert r.result == ValidationResult.VALID
```

---

## Fix 4 — Skip bash `$()` pattern for PowerShell commands

### Problem
`CommandValidator.BASH_DANGEROUS` at `security_validators.py:259` includes:

```python
re.compile(r'\$\(.*\)'),  # $() command substitution
```

In bash, `$(...)` is command substitution — risky. In PowerShell, `$(...)` is a subexpression operator used constantly for interpolation:

```powershell
Write-Output "Total: $($items.Count)"
```

`validate_bash` is called for any shell command that reaches `CommandValidator`. If the executor calls it for PowerShell strings, every line of PowerShell that contains `$()` is flagged.

### Layer
`Infrastructure` — same file.

### Fix
Two-part fix:

**Part A**: In `validate_bash`, add a PowerShell-detection heuristic — if the command looks like PowerShell (contains common cmdlets), skip the bash-specific patterns:

```python
def validate_bash(self, command: str) -> ValidationReport:
    """Validate Bash command for dangerous patterns."""
    # PowerShell commands should not be validated against bash patterns.
    # Detect via common PowerShell cmdlet prefixes.
    _POWERSHELL_INDICATORS = (
        'get-', 'set-', 'new-', 'remove-', 'invoke-',
        'write-output', 'write-host', 'get-childitem',
    )
    cmd_lower = command.lower()
    if any(ind in cmd_lower for ind in _POWERSHELL_INDICATORS):
        return ValidationReport(
            result=ValidationResult.VALID,
            message="Skipping bash validation for PowerShell command",
        )

    for pattern in self.BASH_DANGEROUS:
        if pattern.search(command):
            return ValidationReport(
                result=ValidationResult.DANGEROUS_PATTERN,
                message="Dangerous Bash pattern detected",
                matched_pattern=pattern.pattern,
            )
    return ValidationReport(result=ValidationResult.VALID, message="Bash command is valid")
```

**Part B**: Narrow the `$()` pattern to require a non-whitespace content to be more precise:

```python
# BEFORE:
re.compile(r'\$\(.*\)'),  # $() command substitution

# AFTER:
re.compile(r'\$\([^)]{3,}\)'),  # $() with ≥3 chars content (filters $() empty)
```

### Test
```python
def test_powershell_subexpression_not_flagged():
    v = CommandValidator()
    r = v.validate_bash('Get-ChildItem | Where-Object {$_.Length -gt $($limit * 2)}')
    assert r.result == ValidationResult.VALID

def test_bash_command_substitution_still_blocked():
    v = CommandValidator()
    r = v.validate_bash('echo $(cat /etc/passwd)')
    assert r.result == ValidationResult.DANGEROUS_PATTERN
```

---

## Fix 5 — Code reviewer: prioritize significant tool events over last-10-chronological

### Problem
`CodeReviewerService._render_tool_events` at `weebot/application/services/code_reviewer_service.py` passes `max_events=10` and returns the **last 10** events chronologically. When a step involves 50+ tool calls (filesystem exploration followed by file writes), the last 10 events are all `Get-ChildItem` directory listings — the LLM reviewer never sees the `file_editor` writes that actually completed the step. It concludes the step did nothing substantive and returns `verdict: REVISE`.

### Layer
`Application/Services` — `CodeReviewerService` is an application-layer service. The fix is internal to the class; no port or domain model changes.

### Fix

Replace the chronological tail-slice with a ranked selection that:
1. Always includes all `file_editor` write/create events
2. Always includes any `terminate` or explicit completion events
3. Fills remaining slots with the most recent events

```python
# weebot/application/services/code_reviewer_service.py

def _render_tool_events(
    self,
    events: list[AgentEvent],
    max_events: int = 10,
) -> str:
    """Render tool events for the reviewer LLM.

    Prioritizes write operations and explicit completions over
    chronological recency so the reviewer sees what the step
    actually accomplished, not just the last N tool calls.
    """
    tool_events = [e for e in events if e.type == "tool"]
    if not tool_events:
        return "(no tool calls)"

    # Tier 1: write operations (file_editor create/update, terminate, python_execute success)
    WRITE_TOOLS = {"file_editor", "python_execute", "terminate", "bash"}
    significant = [
        e for e in tool_events
        if getattr(e, "tool_name", "") in WRITE_TOOLS
        and getattr(e, "status", None) == ToolStatus.CALLED  # completed, not just started
        and not getattr(e, "is_error", False)
    ]

    # Tier 2: recent events (last N of all remaining, to preserve context)
    recent = tool_events[-(max_events):]

    # Merge: significant first, then fill with recent (dedup by tool_call_id)
    seen_ids: set[str] = set()
    merged: list[AgentEvent] = []
    for e in significant + recent:
        eid = getattr(e, "tool_call_id", id(e))
        if eid not in seen_ids:
            seen_ids.add(eid)
            merged.append(e)
        if len(merged) >= max_events * 2:  # allow up to 2x for significant events
            break

    lines = []
    for e in merged:
        tool_name = getattr(e, "tool_name", "unknown")
        args = getattr(e, "function_args", {})
        result = getattr(e, "result", "")
        # Truncate individual result to avoid review prompt explosion
        result_preview = str(result)[:200] if result else ""
        lines.append(f"  [{tool_name}] args={args} → {result_preview}")

    return "\n".join(lines)
```

Additionally, increase the default `max_events` cap from 10 to 20 so even without prioritization more context is visible:

```python
tool_lines = self._render_tool_events(step_events, max_events=20)
```

### Test
```python
# tests/unit/test_code_reviewer_service.py
def test_render_tool_events_prioritizes_writes():
    # Build 50 tool events: 40 Get-ChildItem, 5 file_editor writes, 5 bash
    events = (
        _make_tool_events("bash", 40)  # directory listings
        + _make_tool_events("file_editor", 5, success=True)
        + _make_tool_events("bash", 5, success=True)
    )
    service = CodeReviewerService(llm=MockLLM())
    rendered = service._render_tool_events(events, max_events=10)
    assert "file_editor" in rendered
```

---

## Fix 6 — Code reviewer: log parse errors, retry once before auto-approving

### Problem
`CodeReviewerService` wraps the LLM call and JSON parse in a bare `except Exception: return CodeReviewResult(verdict="approved")`. A JSON parse error caused by a malformed LLM response silently auto-approves, hiding the underlying parsing failure and masking real review results.

### Layer
`Application/Services` — same file.

### Fix

```python
# weebot/application/services/code_reviewer_service.py

async def review_step(self, ...) -> CodeReviewResult:
    """Review a completed step for quality and correctness."""
    for attempt in range(2):  # retry once on parse failure
        try:
            prompt = self._build_prompt(step, step_events, task)
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                temperature=0.1,
            )
            return self._parse_response(response)
        except (ValueError, KeyError, json.JSONDecodeError) as parse_exc:
            logger.warning(
                "CodeReviewerService: parse error on attempt %d/2 — %s",
                attempt + 1, parse_exc,
            )
            if attempt == 1:
                # Both attempts failed — fail open but log the traceback
                logger.error(
                    "CodeReviewerService: failed to parse review after 2 attempts; "
                    "auto-approving. Full traceback:",
                    exc_info=True,
                )
                return CodeReviewResult(verdict="approved")
        except Exception as exc:
            # LLM error (timeout, network, rate limit) — fail open immediately
            logger.warning(
                "CodeReviewerService: LLM error, auto-approving: %s", exc
            )
            return CodeReviewResult(verdict="approved")
```

### Test
```python
def test_code_reviewer_retries_on_parse_error():
    call_count = 0
    class BadLLM:
        async def chat(self, **_):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise json.JSONDecodeError("bad json", "", 0)
            return MockResponse(content='{"verdict":"approved"}')
    svc = CodeReviewerService(llm=BadLLM())
    result = asyncio.run(svc.review_step(...))
    assert call_count == 2
    assert result.verdict == "approved"
```

---

## Fix 7 — `python_tool.py`: contextual `undo_hint` based on evaluated code

### Problem
`weebot/tools/python_tool.py` shows `approval.undo_hint` verbatim when the code requires confirmation. The `undo_hint` is set statically in `_DEFAULT_RULES` at policy definition time (e.g., `"Consider 'mv' to a temp folder first."` for any `rm` match). When the agent evaluates Python that happens to use `import sys`, the undo hint is generic and unrelated to the actual operation, confusing the agent into treating a legitimate `sys.argv` access as a destructive operation.

### Layer
`Tools` (interfaces-adjacent) — `python_tool.py` calls `approval_policy.py`. This fix changes only `python_tool.py`'s presentation of the hint; it does not alter the domain or application layers.

### Fix

In `python_tool.py`, augment the hint with a one-line contextual description derived from the code being evaluated:

```python
# weebot/tools/python_tool.py

def _contextual_hint(code: str, base_hint: str) -> str:
    """Derive a contextual message from the code being evaluated."""
    code_lower = code.lower()
    if "import sys" in code_lower or "sys.argv" in code_lower:
        return f"{base_hint} (code uses sys module — review argv/path access)"
    if "open(" in code_lower and ("'w'" in code or '"w"' in code):
        return f"{base_hint} (code opens files for writing)"
    if "shutil.rmtree" in code_lower or "os.remove" in code_lower:
        return f"{base_hint} (code may delete files — verify target paths first)"
    return base_hint


# In the execute() method where requires_confirmation is checked:
if approval.requires_confirmation:
    hint = _contextual_hint(code, approval.undo_hint)
    return ToolResult(
        output="",
        error=(
            f"Code requires user confirmation before execution. "
            f"Hint: {hint}"
        ),
    )
```

### Test
```python
def test_contextual_hint_for_sys():
    hint = _contextual_hint("import sys\nprint(sys.argv)", "base hint")
    assert "sys module" in hint

def test_contextual_hint_passthrough():
    hint = _contextual_hint("x = 1 + 1", "base hint")
    assert hint == "base hint"
```

---

## Fix 8 — Surface security-cascade context in trajectory abort message

### Problem
When `ExecutorAgent` aborts a step due to `TrajectoryHealth.SEMANTIC_LOOP`, the error message is:

```
Trajectory semantic_loop for step 'step-1': ...identical outputs detected. Auto-aborting step.
```

This hides the underlying cause (consecutive security errors producing identical error strings). The planner sees a "semantic loop" and generates a new plan that tries the same commands again, repeating the cycle.

### Layer
`Application/Agents` — `executor.py:850-857`.

### Fix

In `executor.py`, before emitting the trajectory abort, check whether the current `last_error_class` is security-related and include it in the message:

```python
# weebot/application/agents/executor.py  (inside execute_step, after trajectory abort decision)

if diagnosis.health in _auto_abort_health:
    # Enrich the abort message with policy context if the trajectory
    # degenerated due to security blocks rather than true semantic repetition
    security_context = ""
    if last_error_class in ("security_blocked", "policy_denied", "confirmation_required"):
        count = consecutive_error_class_counts.get(last_error_class, 0)
        security_context = (
            f" (underlying cause: {count}× consecutive '{last_error_class}' "
            f"errors — check security_validators.py allowlists)"
        )
    loop_error = (
        f"Trajectory {diagnosis.health.value} for step '{step.id}': "
        f"{diagnosis.detail}{security_context}. Auto-aborting step."
    )
    yield ErrorEvent(error=loop_error)
    abort_step = True
    break
```

No new imports required — `last_error_class` and `consecutive_error_class_counts` are already in scope in `execute_step`.

### Test
```python
# This is a behavioral test on the error message content — verify via integration test
# or by running the executor with a stub tool that returns consecutive security errors.
```

---

## Fixes 9–12 — Generated output code bugs

These bugs are in `Output/windows-autonomous-agent/` — the project created by the weebot agent during the execution session. These are not framework bugs; they are bugs in agent-generated output that need to be patched.

### Fix 9 — `get_current_step()` returns list, not item

**File**: `Output/windows-autonomous-agent/src/domain/models.py`

```python
# BEFORE (bug: returns entire steps list):
def get_current_step(self) -> Optional[Step]:
    if self.current_step_index < len(self.steps):
        return self.steps  # ← wrong

# AFTER:
def get_current_step(self) -> Optional[Step]:
    if self.current_step_index < len(self.steps):
        return self.steps[self.current_step_index]  # ← correct
    return None
```

### Fix 10 — `in_progress` assignment is incomplete

**File**: `Output/windows-autonomous-agent/src/domain/agent.py`

```python
# BEFORE (SyntaxError: empty right-hand side):
in_progress =

# AFTER:
in_progress = [
    s for s in plan.steps
    if s.status == StepStatus.IN_PROGRESS
]
```

### Fix 11 — Wrong import path in test file

**File**: `Output/windows-autonomous-agent/tests/test_domain.py`

`pytest.ini` sets `pythonpath = src`, so Python resolves imports relative to `src/`. The test file imports:

```python
# BEFORE (resolves to src/src/domain/models.py — not found):
from src.domain.models import Plan, Step, PlanStatus, StepStatus

# AFTER:
from domain.models import Plan, Step, PlanStatus, StepStatus
```

Apply the same fix to all `from src.domain.*` and `from src.*` imports in the test file.

### Fix 12 — Plan status never transitions DRAFT → IN_PROGRESS

**File**: `Output/windows-autonomous-agent/src/domain/models.py`

The test asserts `plan.status == PlanStatus.IN_PROGRESS` after calling `mark_step_completed()` on an intermediate step, but `mark_step_completed()` only advances `current_step_index` without updating `self.status`.

```python
# BEFORE: mark_step_completed only advances the index
def mark_step_completed(self, step_id: str, result: str = "") -> None:
    for i, step in enumerate(self.steps):
        if step.id == step_id:
            self.steps[i].status = StepStatus.COMPLETED
            self.steps[i].result = result
            self.current_step_index = i + 1
            break
    # ← missing: status transition

# AFTER: also transition plan status
def mark_step_completed(self, step_id: str, result: str = "") -> None:
    for i, step in enumerate(self.steps):
        if step.id == step_id:
            self.steps[i].status = StepStatus.COMPLETED
            self.steps[i].result = result
            self.current_step_index = i + 1
            # Transition plan status
            if self.current_step_index >= len(self.steps):
                self.status = PlanStatus.COMPLETED
            elif self.status == PlanStatus.DRAFT:
                self.status = PlanStatus.IN_PROGRESS
            break
```

---

## Implementation Order

Execute in this order to avoid unblocking a partially-fixed system:

```
Phase 1 — Security false-positives (Fix 1, 2, 3, 4)
  These fixes reduce the noise that cascades into trajectory aborts.
  All changes in one file: security_validators.py.

Phase 2 — Code reviewer accuracy (Fix 5, 6)
  Only meaningful once Phase 1 reduces the false-positive rate.
  All changes in one file: code_reviewer_service.py.

Phase 3 — Error messaging (Fix 7, 8)
  UX improvements — agent makes better decisions with better error context.
  python_tool.py and executor.py.

Phase 4 — Generated output fixes (Fix 9–12)
  Independent of the framework. Fix the output project to make its test suite pass.
  All changes in Output/windows-autonomous-agent/.
```

---

## Verification Checklist

After each phase:

```bash
# Phase 1: run the security validator unit tests
pytest tests/unit/test_security_validators.py -v

# Phase 2: run the code reviewer unit tests
pytest tests/unit/test_code_reviewer_service.py -v

# Phase 3: run the python tool unit tests
pytest tests/unit/test_python_tool.py -v

# Phase 4: run the generated project's own test suite
cd Output/windows-autonomous-agent
python -m pytest tests/ -v
```

Full regression after all phases:
```bash
pytest tests/ -v --cov=weebot --cov-report=term-missing
```

---

## Architectural Compliance Notes

- **Fixes 1–4**: `infrastructure/security/security_validators.py` is Infrastructure layer. No imports from Application or Interfaces. ✓  
- **Fixes 5–6**: `application/services/code_reviewer_service.py` is Application layer. Imports from Domain and Application/Ports only. ✓  
- **Fix 7**: `tools/python_tool.py` is in the Tools subdirectory (Interfaces-adjacent). The `_contextual_hint` helper is a pure function with no external imports. ✓  
- **Fix 8**: `application/agents/executor.py` is Application layer. The enrichment uses only variables already in scope. ✓  
- **Fixes 9–12**: Changes are in `Output/` (generated code, not part of the weebot package). They do not affect any weebot layer. ✓  

No fix violates the Dependency Rule. Domain layer is untouched.
