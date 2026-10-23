---
type: object
name: BaseTool
code: BaseTool, ToolResult, ToolCollection
cluster: tools
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# BaseTool

The tool contract. `BaseTool` is what every agent tool subclasses, `ToolResult` is what every tool returns, and `ToolCollection` holds a session's tools and dispatches a call by name. Guards and approval sit between the collection and the tool as a decorator, `GuardedTool`.

## Why this shape
`BaseTool` and `ToolResult` live in the domain layer so ports and application services can name them without importing `weebot/tools/` (`weebot/domain/models/base_tool.py:1-10`, `weebot/domain/models/tool_result.py:1-7`). `weebot/tools/base.py` only re-exports them; `ToolCollection` is re-exported lazily through a module `__getattr__` to avoid an import cycle (`weebot/tools/base.py:11-27`). Guards are a decorator over a tool, not a step inside each tool, so one chain covers the shell tools, the MCP server and MCP-sourced tools (`weebot/application/services/tool_guards.py:1-23`).

## Shape
- `BaseTool(ABC, BaseModel)` (`weebot/domain/models/base_tool.py:20`): fields `name`, `description`, `parameters` (JSON Schema) (`:31-33`); `max_concurrent` (0 = unlimited) (`:39`), `default_timeout_seconds` = 60 (`:42`), `truncation_strategy` = `"head"` (`:46`). Abstract `async execute(**kwargs) -> ToolResult` (`:48-50`); `health_check()` defaults to True (`:52-58`); `close()` is a no-op (`:60-70`); `to_param()` builds the OpenAI function spec (`:72-81`). Which roles get a tool is not a field: see the RoleBasedToolRegistry card (`:34-35`).
- `ToolResult` dataclass (`weebot/domain/models/tool_result.py:15`): `output`, `error`, `base64_image`, `success`, `data`, `metadata` (`:33-40`). `__post_init__` keeps `error` and `success` consistent both ways (`:42-50`). `str(result)` is `output`, or `"ERROR: <error>"` (`:57-60`). Factories `success_result(output, data, **metadata)` and `error_result(error, output, **metadata)` (`:78-108`).
- `ToolCollection` (`weebot/application/models/tool_collection.py:82`): a dict keyed by `BaseTool.name` (`:92`), with optional canonicalizer, contract loader and result cache (`:89-100`).
  - `to_params()` skips tools that failed `check_health()` once it has run, and lets the contract loader extend descriptions (`:129-154`).
  - `execute(_name, **kwargs)` (`:156`): fuzzy name match on a miss (`:157-165`); refuse an unhealthy tool (`:168-175`); canonicalizer may block or rewrite args (`:178-187`); cache lookup (`:194-199`); per-tool semaphore when `max_concurrent > 0` (`:202-208`); run; stamp `execution_time_ms`, `retry_count`, `tool_name` (`:225-232`); truncate output over `MAX_TOOL_OUTPUT_CHARS` (20 000, `weebot/config/constants.py:80`) by the tool's strategy (`:235-244`, `_truncate` `:23-52`); cache store on success (`:257-258`).
  - Exceptions: logged with traceback (`:264`); non-retryable ones return an error result at once (`:269-276`); `OSError`, `TimeoutError`, `ConnectionError` retry up to `DEFAULT_MAX_RETRIES` = 2 with capped backoff (`:86-87, 288-300`).
  - `teardown()` shuts down only an `apify_service` attribute (`:112-127`).

### How a call reaches a tool
1. `ToolExecutor.execute_tool` takes the timeout from the tool's `default_timeout_seconds` (`weebot/application/agents/executor/_tool_executor.py:285`), runs the egress check (`:323`) and, if a human approved there, records that call's fingerprint (`:333-335`).
2. It calls `self._tools.execute(...)` under `approval_scope(session_id, approved_call)` with an `asyncio.wait_for` timeout (`:360-365`).
3. `ToolCollection.execute` dispatches to the tool, which for `bash`, `powershell`, `python_execute` and any financial or outbound tool is a `GuardedTool` (`weebot/application/services/tool_guards.py:43, 429-450`).
4. `GuardedTool.execute` runs `GuardChain.evaluate`: every guard is asked, the most restrictive verdict wins, a guard that raises yields DENY (`:281-306`). The full chain is BashGuard, CommandSecurityAnalyzer, ExecApprovalPolicy, financial, outbound and (optionally) egress adapters (`:309-322`); the first three only look at `command` of `bash`/`powershell` (`:41, 79-83`).
5. Mode `shell_guard_mode` (default `enforce`, `weebot/config/settings.py:191-195`): in `enforce` a DENY returns an error and is never approvable (`tool_guards.py:380-384`); an ASK, or any ASK marked `enforce_always` by the outbound adapter (`:270-275`), goes to `_resolve_ask` (`:385-391`).
6. `_resolve_ask` skips the question if the executor already approved this exact call (`:401-402`, `tool_approval.py:192-194`), else asks `current_approval()` (`:414-415`): `DenyApproval` (process default, `tool_approval.py:103-111, 172`), `ConsoleApproval` (TTY prompt, `:135-159`) or `FlowPauseApproval` (answers PENDING, then consumes a single-use grant on retry, `:114-127`). PENDING returns `pending_result` with `data["approval_required"]` (`:246-263`), which the executor turns into `ToolApprovalEvent` + `WaitForUserEvent` (`weebot/application/agents/executor/_base.py:980-994`).
7. The LLM sees `str(result)` (`_base.py:1005`), fenced when the tool is untrusted (`:1006-1007`). `result.data` goes only to the executor's `_facts` (`:971-972`).

Consequences (read from source, not run):
- Only `output`/`error` reach the model. A tool that puts its payload only in `data` gives the agent nothing to act on; see the WebTools card (`search_images`).
- The executor's after-tool middleware rebuilds a result with `ToolResult(..., is_error=...)` (`_base.py:954-960`); `ToolResult` has no `is_error` field, only a property (`tool_result.py:52-55`), so that line raises `TypeError` whenever middleware changes the output. It also drops `data` and `metadata`.
- `BaseTool.close()` says the registry or task runner calls it (`base_tool.py:60-66`); `ToolCollection.teardown` never does (`tool_collection.py:119-127`). Only `GuardedTool.close` forwards it (`tool_guards.py:425-426`).
- Retries re-run the whole tool on `OSError`/`ConnectionError` (`tool_collection.py:87, 269-300`), including non-idempotent ones like `bash` or `file_editor`.
- `error_result(error, data=...)` puts `data` into `metadata["data"]`, not `data`, because `data` is not a parameter (`tool_result.py:96-108`).
- The `tool_guards` docstring still says `observe` is the default (`tool_guards.py:13`); the setting defaults to `enforce` (`settings.py:191-193`).

## Connected to
- **Built by** `RoleBasedToolRegistry.create_tool_collection*`, which wraps with `guard_tools(..., include_egress=False)` (`weebot/tools/tool_registry.py:512-514`); `interfaces/factories.py:418-425`, which wraps again after MCP/Apify tools join and fails closed without the guard (`:414-421`); the DI `guard_tools` registration (`weebot/application/di/__init__.py:283-288`); the MCP server, with egress included (`weebot/mcp/server.py:271-274, 388-392`). Empty collections: `cqrs/handlers/execute_step_handler.py:26, 64`, `di/__init__.py:450`.
- **Used by** `ToolExecutor` (above); teardown from `plan_act_flow.py:530`, `agent_session_manager.py:45`, `dispatch_session_input.py:95, 118`.
- **Related:** the ExecTools and WebTools cards (concrete tools), the RoleBasedToolRegistry card, the BashGuard / ExecApprovalPolicy / EgressGuard / ApprovalManager cards, `call_fingerprint` (`weebot/core/approval.py:124`).
- **Looks like but is not:** `weebot/tools/validation.py` (a second, unused validation pipeline; see ExecTools); `ApprovalManager` itself, which only stores grants (`tool_approval.py:93`).

## If you change this
**Hits:** every tool (field defaults, `to_param`), every flow's tool dispatch, the guard decorator, MCP server tools. Tests: `tests/unit/tools/test_base_tool.py`, `tests/unit/tools/test_tool_result_enhanced.py`, `tests/unit/test_tool_collection_retry.py`, `tests/unit/test_tool_health.py`, `tests/unit/test_tool_truncation.py`, `tests/unit/test_parallel_tool_execution.py`, `tests/unit/application/services/test_tool_guards.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/fixes/test_f01_powershell_skips_bash_guard.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/mcp/test_mcp_tool_guards.py`, `tests/unit/tools/test_tool_registry.py`; 38 test files name `ToolCollection`.
**Does not hit:** which role sees a tool (registry table); the rules inside BashGuard / ExecApprovalPolicy.

## Surfaces
Every agent tool call; the approval prompt in the CLI and the web UI pause (`tool_approval.py:227-243`); MCP clients via `run_mcp.py`.

## See
`weebot/domain/models/base_tool.py`, `weebot/application/models/tool_collection.py`, `weebot/application/services/tool_guards.py`
