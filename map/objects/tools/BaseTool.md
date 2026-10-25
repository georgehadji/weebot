---
type: object
name: BaseTool
code: BaseTool, ToolResult, ToolCollection
cluster: tools
universe: live
status: verified
verified: 2026-10-25
commit: 12624041
---

# BaseTool

The tool contract. `BaseTool` is what every agent tool subclasses, `ToolResult` is what every tool returns, and `ToolCollection` holds a session's tools and dispatches a call by name. Guards and approval sit between the collection and the tool as a decorator, `GuardedTool`.

## Why this shape
`BaseTool` and `ToolResult` live in the domain layer so ports and application services can name them without importing `weebot/tools/` (`weebot/domain/models/base_tool.py:1-10`, `weebot/domain/models/tool_result.py:1-7`). `weebot/tools/base.py` only re-exports them; `ToolCollection` is re-exported lazily through a module `__getattr__` to avoid an import cycle (`weebot/tools/base.py:11-27`). Guards are a decorator over a tool, not a step inside each tool, so one chain covers the shell tools, the MCP server and MCP-sourced tools (`weebot/application/services/tool_guards.py:1-23`).

## Shape
- `BaseTool(ABC, BaseModel)` (`weebot/domain/models/base_tool.py:22`): fields `name`, `description`, `parameters` (JSON Schema) (`:33-35`); `max_concurrent` (0 = unlimited) (`:41`), `default_timeout_seconds` = 60 (`:44`), `truncation_strategy` = `"head"` (`:48`). `output_trust` is a `ClassVar[OutputTrust]` defaulting to `EXTERNAL`, so an undeclared tool is fenced and tainting; `resolved_output_trust()` lets a wrapper delegate (`:50-57`; enum in `weebot/domain/models/output_trust.py:18-33`, decisions in `weebot/core/trust_boundary.py:58-104`). Abstract `async execute(**kwargs) -> ToolResult` (`:59-61`); `health_check()` defaults to True (`:63-69`); `close()` is a no-op (`:71-81`); `to_param()` builds the OpenAI function spec (`:83-92`). Which roles get a tool is not a field: see the RoleBasedToolRegistry card (`:36-37`).
- `ToolResult` dataclass (`weebot/domain/models/tool_result.py:16`): `output`, `error`, `base64_image`, `success`, `data`, `metadata` (`:33-40`). `__post_init__` keeps `error` and `success` consistent both ways (`:42-50`). `str(result)` is `output`, or `"ERROR: <error>"` (`:57-60`). Factories `success_result(output, data, **metadata)` and `error_result(error, output, **metadata)` (`:78-108`).
- `ToolCollection` (`weebot/application/models/tool_collection.py:82`): a dict keyed by `BaseTool.name` (`:92`), with optional canonicalizer, contract loader and result cache (`:89-100`).
  - `set_visible(names)` limits which definitions are sent while every tool stays callable; `hidden_names()` lists the rest (`:167-174`).
  - `to_params()` skips hidden tools and tools that failed `check_health()` once it has run, and lets the contract loader extend descriptions (`:176-193`).
  - `canonical_args(name, args)` returns the arguments as `execute` will run them; the executor's effect ledger keys on it (`:112-128`).
  - `execute(_name, **kwargs)` (`:195`): fuzzy name match on a miss (`:196-204`); refuse an unhealthy tool (`:206-214`); canonicalizer may block or rewrite args (`:216-226`); cache lookup (`:232-238`); per-tool semaphore when `max_concurrent > 0` (`:240-247`); a model-supplied `_max_retries` is dropped (`:251-253`); run; stamp `execution_time_ms`, `retry_count`, `tool_name` (`:265-273`); truncate output over `MAX_TOOL_OUTPUT_CHARS` (20 000, `weebot/config/constants.py:85`) by the tool's strategy (`weebot/application/models/tool_collection.py:275-285`, `_truncate` `:23-52`); cache store on success (`:297-299`).
  - Exceptions: logged with traceback (`:305`); non-retryable ones return an error result at once (`:310-317`); `OSError`, `TimeoutError`, `ConnectionError` retry up to `DEFAULT_MAX_RETRIES` = 2 with capped backoff (`:86-87, 329-341`).
  - `teardown()` shuts down an `apify_service` attribute (looking through a `GuardedTool` to `.inner`) and calls every tool's `close()` (`:130-154`).

### How a call reaches a tool
1. `ToolExecutor.execute_tool` takes the timeout from the tool's `default_timeout_seconds` (`weebot/application/agents/executor/_tool_executor.py:377`), gets the egress guard (`:403`, `_get_egress_guard` `:262`), runs `guard.classify` (`:421-424`) and, if a human approved there, records that call's fingerprint (`:449-451`). An egress this session already completed is not re-run: the ledger returns a replay note (`:428-441`).
2. It calls `self._tools.execute(...)` under `approval_scope(session_id, approved_call)` with an `asyncio.wait_for` timeout (`:476-482`).
3. `ToolCollection.execute` dispatches to the tool, which for `bash`, `powershell`, `python_execute` and any financial or outbound tool is a `GuardedTool` (`weebot/application/services/tool_guards.py:43, 481-502`).
4. `GuardedTool.execute` (`:413`) runs `GuardChain.evaluate`: every guard is asked, the most restrictive verdict wins, a guard that raises yields DENY (`:324-349`). The full chain is BashGuard, CommandSecurityAnalyzer, ExecApprovalPolicy, financial, outbound and (optionally) egress adapters (`:352-365`); the first three only look at `command` of `bash`/`powershell` (`:41, 79-83`).
5. Mode `shell_guard_mode` (default `enforce`, `weebot/config/settings.py:208-212`): in `enforce` a DENY returns an error and is never approvable (`weebot/application/services/tool_guards.py:428-432`); an ASK, or any ASK marked `enforce_always` by the outbound adapter (`:313-318`), goes to `_resolve_ask` (`:433-437`).
6. `_resolve_ask` skips the question if the executor already approved this exact call (`:452-454`, `weebot/application/services/tool_approval.py:192-194`), else asks `current_approval()` (`weebot/application/services/tool_guards.py:466`): `DenyApproval` (process default, `weebot/application/services/tool_approval.py:103-111, 172`), `ConsoleApproval` (TTY prompt, `:135-159`) or `FlowPauseApproval` (answers PENDING, then consumes a single-use grant on retry, `:114-127`). PENDING returns `pending_result` with `data["approval_required"]` (`:246-263`), which the executor turns into `ToolApprovalEvent` + `WaitForUserEvent` (`weebot/application/agents/executor/_step_result_handler.py:16-40`, called at `_base.py:1082`).
7. The LLM sees `str(result)`, fenced unless the tool's `OutputTrust` is `LOCAL` (`_base.py:396-418`, called at `:1097`); a non-error `EXTERNAL` result also taints the session (`_tool_executor.py:543-546`). `result.data` goes to the executor's `_facts`, not to the model (`_base.py:1081`).

Consequences (read from source, not run):
- Only `output`/`error` reach the model. A tool that puts its payload only in `data` gives the agent nothing to act on; see the WebTools card (`search_images`).
- Retries re-run the whole tool on `OSError`/`ConnectionError` (`weebot/application/models/tool_collection.py:87, 329-341`), including non-idempotent ones like `bash` or `file_editor`.
- `error_result(error, data=...)` puts `data` into `metadata["data"]`, not `data`, because `data` is not a parameter (`weebot/domain/models/tool_result.py:95-108`).

## Connected to
- **Built by** `RoleBasedToolRegistry.create_tool_collection*`, which wraps with `guard_tools(..., include_egress=False)` (`weebot/application/services/tool_registry.py:532-534`); `interfaces/factories.py:352-362`, which wraps again after MCP/Apify tools join and fails closed without the guard (`:333-334`); the DI `guard_tools` registration (`weebot/application/di/__init__.py:295-300`); the MCP server, with egress included (`weebot/mcp/server.py:271-274, 388-392`). Empty collections: `cqrs/handlers/execute_step_handler.py:26, 64`, `di/__init__.py:465`.
- **Used by** `ToolExecutor` (above); teardown from `plan_act_flow.py:523`, `agent_session_manager.py:45`, `dispatch_session_input.py:95, 118`.
- **Related:** the ExecTools and WebTools cards (concrete tools), the RoleBasedToolRegistry card, the BashGuard / ExecApprovalPolicy / EgressGuard / ApprovalManager cards, `call_fingerprint` (`weebot/core/approval.py:126`).
- **Looks like but is not:** `weebot/tools/validation.py` (a second, unused validation pipeline; see ExecTools); `ApprovalManager` itself, which only stores grants (`tool_approval.py:93`).

## If you change this
**Hits:** every tool (field defaults, `to_param`), every flow's tool dispatch, the guard decorator, MCP server tools. Tests: `tests/unit/tools/test_base_tool.py`, `tests/unit/tools/test_tool_result_enhanced.py`, `tests/unit/test_tool_collection_retry.py`, `tests/unit/test_tool_health.py`, `tests/unit/test_tool_truncation.py`, `tests/unit/test_parallel_tool_execution.py`, `tests/unit/application/services/test_tool_guards.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/fixes/test_f01_powershell_skips_bash_guard.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/mcp/test_mcp_tool_guards.py`, `tests/unit/tools/test_tool_registry.py`; 51 test files name `ToolCollection`.
**Does not hit:** which role sees a tool (registry table); the rules inside BashGuard / ExecApprovalPolicy.

## Surfaces
Every agent tool call; the approval prompt in the CLI and the web UI pause (`tool_approval.py:227-243`); MCP clients via `run_mcp.py`.

## See
`weebot/domain/models/base_tool.py`, `weebot/application/models/tool_collection.py`, `weebot/application/services/tool_guards.py`
