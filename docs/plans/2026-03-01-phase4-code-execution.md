# Phase 4: Code Execution Tools — Implementation Plan

**Date:** 2026-03-01
**Status:** DECISIONS APPROVED — Ready to implement
**Baseline:** 331 tests passing
**Target:** 331 + ~20 new tests, all passing

---

## Approved Decisions (all confirmed by user)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Python execution strategy | subprocess python -c (NOT in-process eval) | Full process isolation; timeout+kill works; consistent with BashTool |
| 2 | Memory limits on Windows | psutil background monitor, graceful degradation if missing | psutil already in project; Windows-compatible |
| 3 | SandboxedExecutor role | Plain helper class via PrivateAttr — NOT a BaseTool | Implementation detail; BashTool/PythonTool are the exposed agents |
| 4 | Safety gate | ExecApprovalPolicy().evaluate() DENY=error, ALWAYS_ASK=error+hint | Reuses existing infrastructure |
| 5 | Output size limit | 64 KB default (sandbox_max_output_bytes in WeebotSettings) | Enough for data analysis, safe for LLM context |

---

## Files to Create / Modify

New files:
- weebot/sandbox/__init__.py
- weebot/sandbox/executor.py      SandboxedExecutor + ExecutionResult
- weebot/tools/bash_tool.py       BashTool (PowerShell primary, WSL2 optional)
- weebot/tools/python_tool.py     PythonExecuteTool
- tests/unit/test_sandbox.py      5+ tests
- tests/unit/test_bash_tool.py    7 tests
- tests/unit/test_python_tool.py  7 tests

Modified files:
- weebot/config/settings.py       add 4 sandbox fields

---

## ExecutionResult dataclass (sandbox/executor.py)

Fields:
  stdout: str
  stderr: str
  returncode: int
  elapsed_ms: float
  timed_out: bool = False
  memory_killed: bool = False

Properties:
  success         -> returncode==0 and not timed_out and not memory_killed
  combined_output -> stdout + stderr merged, or "(no output)"

---

## SandboxedExecutor (sandbox/executor.py)

Constructor args: max_output_bytes=65536, memory_limit_mb=None

async run(cmd: list[str], timeout: float, cwd=None, env=None) -> ExecutionResult:

  Step 1. Record start time via time.monotonic()
  Step 2. Launch child via asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
  Step 3. If memory_limit_mb set: start psutil monitor thread via asyncio.to_thread
  Step 4. asyncio.wait_for(proc.communicate(), timeout=timeout)
  Step 5. On asyncio.TimeoutError: proc.kill(), return ExecutionResult(timed_out=True)
  Step 6. Truncate output bytes if > max_output_bytes, append "...[truncated]"
  Step 7. Decode UTF-8 with errors="replace"
  Step 8. Return ExecutionResult(stdout, stderr, returncode, elapsed_ms)

psutil memory monitor (background thread function):
  - Uses threading.Event as stop flag
  - Every 0.5s: psutil.Process(pid).memory_info().rss > limit -> proc.kill()
  - All exceptions caught silently (graceful: psutil not installed, proc already dead)

---

## BashTool (tools/bash_tool.py)

  name = "bash"
  Inherits: BaseTool
  PrivateAttr: _executor: SandboxedExecutor, _policy: ExecApprovalPolicy

  Parameters:
    command (required): str — the shell command
    timeout (optional): float, default 30
    working_dir (optional): str, default None
    use_wsl (optional): bool, default False

  model_post_init: instantiates _executor with settings.sandbox_max_output_bytes,
                   instantiates _policy = ExecApprovalPolicy()

  execute() flow:
    Step 1. _policy.evaluate(command)
              DENY       -> return ToolResult(error="Command denied: {reason}")
              ALWAYS_ASK -> return ToolResult(error="Requires confirmation: {undo_hint}")
    Step 2. Build cmd list:
              use_wsl=True AND _wsl_available() -> ["wsl","bash","-c",command]
              else -> ["powershell","-NoProfile","-NonInteractive","-Command",command]
    Step 3. result = await _executor.run(cmd, timeout, cwd=working_dir)
    Step 4. result.timed_out -> ToolResult(error="Command timed out after Xs")
    Step 5. not result.success -> ToolResult(output=stdout, error=stderr or "Exit code N")
    Step 6. success -> ToolResult(output=combined_output)

  _wsl_available() module-level helper function:
    subprocess.run(["wsl","--status"], capture_output=True, timeout=3)
    returncode==0 -> True; any exception -> False

---

## PythonExecuteTool (tools/python_tool.py)

  name = "python_execute"
  Inherits: BaseTool
  PrivateAttr: _executor: SandboxedExecutor, _policy: ExecApprovalPolicy

  Parameters:
    code (required): str — Python source code
    timeout (optional): float, default 30

  execute() flow:
    Step 1. _policy.evaluate(code)
              DENY       -> return ToolResult(error="Code denied: {reason}")
              ALWAYS_ASK -> return ToolResult(error="Requires confirmation: {undo_hint}")
    Step 2. cmd = ["python", "-c", code]
    Step 3. result = await _executor.run(cmd, timeout)
    Step 4. result.timed_out -> error "Python code timed out after Xs"
    Step 5. not result.success -> ToolResult(output=stdout, error=stderr)
    Step 6. success -> ToolResult(output=combined_output)

---

## WeebotSettings New Fields (config/settings.py)

  bash_timeout: int = 30                 # env: BASH_TIMEOUT
  python_timeout: int = 30               # env: PYTHON_TIMEOUT
  sandbox_max_output_bytes: int = 65536  # env: SANDBOX_MAX_OUTPUT_BYTES (64 KB)
  sandbox_allow_network: bool = False    # env: SANDBOX_ALLOW_NETWORK

---

## Test Specifications

### test_sandbox.py (5 tests)

  test_successful_run_returns_stdout     stdout captured, success=True
  test_nonzero_returncode_not_success    returncode=1, success=False
  test_timeout_sets_timed_out_flag       asyncio.TimeoutError -> timed_out=True
  test_output_truncated_at_max_bytes     large output -> "[truncated]" suffix
  test_elapsed_ms_populated              elapsed_ms > 0 after any run

### test_bash_tool.py (7 tests)

  test_successful_command_returns_output happy path: stdout -> ToolResult.output
  test_denied_command_returns_error      "format c:" -> DENY -> ToolResult.error
  test_always_ask_command_returns_hint   "rm file" -> ALWAYS_ASK -> error+undo_hint
  test_timeout_returns_tool_error        timed_out=True -> "timed out" in error
  test_nonzero_exit_is_error             returncode=1 -> result.is_error==True
  test_tool_name_and_params              name=="bash", "command" in parameters["properties"]
  test_executor_called_with_powershell   cmd[0]=="powershell"

### test_python_tool.py (7 tests)

  test_successful_code_returns_stdout    print("hi") -> "hi" in output
  test_syntax_error_in_stderr            bad syntax -> stderr -> ToolResult.error
  test_runtime_error_in_stderr           ZeroDivisionError -> ToolResult.error
  test_timeout_returns_tool_error        timed_out=True -> "timed out" in error
  test_denied_code_returns_error         "format" in code -> DENY -> error
  test_tool_name_and_params              name=="python_execute", "code" in properties
  test_executor_called_with_python_flag  cmd == ["python", "-c", code]

---

## Mock Patterns for Tests

For BashTool/PythonTool (mock the _executor.run method):
  mock_result = ExecutionResult(stdout="hello", stderr="", returncode=0, elapsed_ms=42.0)
  patch.object(tool._executor, "run", new=AsyncMock(return_value=mock_result))

For SandboxedExecutor unit tests (mock the subprocess):
  mock_proc = AsyncMock()
  mock_proc.returncode = 0
  mock_proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
  mock_proc.kill = AsyncMock()
  patch("asyncio.create_subprocess_exec", return_value=mock_proc)

Timeout injection:
  async def instant_timeout(coro, timeout):
      coro.close()
      raise asyncio.TimeoutError
  patch("asyncio.wait_for", side_effect=instant_timeout)
  -> then assert result.timed_out == True

---

## Implementation Order

  1. weebot/sandbox/__init__.py + weebot/sandbox/executor.py
  2. tests/unit/test_sandbox.py  (verify executor in isolation first)
  3. weebot/config/settings.py   (add 4 new sandbox fields)
  4. weebot/tools/bash_tool.py
  5. tests/unit/test_bash_tool.py
  6. weebot/tools/python_tool.py
  7. tests/unit/test_python_tool.py
  8. python -m pytest tests/ -q --tb=short  (target: 351+ passing, 0 failing)
  9. git commit

---

## Phase 5 (MCP Server) — After Phase 4

New files:
  weebot/mcp/__init__.py
  weebot/mcp/server.py       MCPServer, SSETransport, all tools exposed as MCP tools
  weebot/mcp/resources.py    ActivityStreamResource, StateResource, ScheduleResource
  tests/unit/test_mcp_server.py (8+ tests)

Capabilities:
  - Expose all 10+ tools (PowerShell, Screen, ComputerUse, Browser, Bash, Python, Scheduler)
  - ActivityStream as real-time MCP resource (newest-first, 200 events)
  - State snapshots as MCP resource
  - SSE transport for Claude IDE integration
