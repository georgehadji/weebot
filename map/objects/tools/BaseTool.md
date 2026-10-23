---
type: object
name: BaseTool
code: BaseTool, ToolResult, ToolCollection
cluster: tools
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# BaseTool

The tool contract. `BaseTool` is what every agent tool subclasses, `ToolResult` is what every tool returns, and `ToolCollection` holds a session's tools and dispatches a call by name. Guards and approval sit between the collection and the tool as a decorator, `GuardedTool`.

## Why this shape
`BaseTool` and `ToolResult` live in the domain layer so ports and application services can name them without importing `weebot/tools/` (`weebot/domain/models/base_tool.py:1-10`, `weebot/domain/models/tool_result.py:1-7`). `weebot/tools/base.py` only re-exports them; `ToolCollection` is re-exported lazily through a module `__getattr__` to avoid an import cycle (`weebot/tools/base.py:11-27`). Guards are a decorator over a tool, not a step inside each tool, so one chain covers the shell tools, the MCP server and MCP-sourced tools (`weebot/application/services/tool_guards.py:1-23`).

## Shape
- `BaseTool(ABC, BaseModel)` (`weebot/domain/models/base_tool.py:20`): fields `name`, `description`, `parameters` (JSON Schema) (`:31-33`); `max_concurrent` (0 = unlimited) (`:39`), `default_timeout_seconds` = 60 (`:42`), `truncation_strategy` = `"head"` (`:46`). Abstract `async execute(**kwargs) -> ToolResult` (`:48-50`); `health_check()` defaults to True (`:52-58`); `close()` is a no-op (`:60-70`); `to_param()` builds the OpenAI function spec (`:72-81`). Which roles get a tool is not a field: see the RoleBasedToolRegistry card (`:34-35`).
- `ToolResult` dataclass (`weebot/domain/models/tool_result.py:15`): `output`, `error`, `base64_image`, `success`, `data`, `metadata` (`:33-40`). `__post_init__` keeps `error` and `success` consistent both ways (`:42-50`). `str(result)` is `output`, or `"ERROR: <error>"` (`:57-60`). Factories `success_result(output, data, **metadata)` and `error_result(error, output, **metadata)` (`:78-108`).
- `ToolCollection` (`weebot/application/models/tool_collection.py:82`): a dict keyed by `BaseTool.name` (`:92`), with optional canonicalizer, contract loader and result cache (`:89-100`).
  - `set_visible(names)` limits which definitions are sent while every tool stays callable; `hidden_names()` lists the rest (`:149-156`).
  - `to_params()` skips hidden tools and tools that failed `check_health()` once it has run, and lets the contract loader extend descriptions (`:158-175`).
  - `execute(_name, **kwargs)` (`:177`): fuzzy name match on a miss (`:178-186`); refuse an unhealthy tool (`:188-196`); canonicalizer may block or rewrite args (`:198-208`); cache lookup (`:214-220`); per-tool semaphore when `max_concurrent > 0` (`:222-229`); a model-supplied `_max_retries` is dropped (`:233-235`); run; stamp `execution_time_ms`, `retry_count`, `tool_name` (`:247-255`); truncate output over `MAX_TOOL_OUTPUT_CHARS` (20 000, `weebot/config/constants.py:85`) by the tool's strategy (`weebot/application/models/tool_collection.py:257-267`, `_truncate` `:23-52`); cache store on success (`:279-281`).
  - Exceptions: logged with traceback (`:287`); non-retryable ones return an error result at once (`:292-299`); `OSError`, `TimeoutError`, `ConnectionError` retry up to `DEFAULT_MAX_RETRIES` = 2 with capped backoff (`:86-87, 311-323`).
  - `teardown()` shuts down an `apify_service` attribute (looking through a `GuardedTool` to `.inner`) and calls every tool's `close()` (`:112-136`).

### How a call reaches a tool
1. `ToolExecutor.execute_tool` takes the timeout from the tool's `default_timeout_seconds` (`weebot/application/agents/executor/_tool_executor.py:312`), gets the egress guard (`:332`, `_get_egress_guard` `:193`), runs `guard.classify` (`:350-352`) and, if a human approved there, records that call's fingerprint (`:360-362`).
2. It calls `self._tools.execute(...)` under `approval_scope(session_id, approved_call)` with an `asyncio.wait_for` timeout (`:387-393`).
3. `ToolCollection.execute` dispatches to the tool, which for `bash`, `powershell`, `python_execute` and any financial or outbound tool is a `GuardedTool` (`weebot/application/services/tool_guards.py:43, 476-497`).
4. `GuardedTool.execute` (`:408`) runs `GuardChain.evaluate`: every guard is asked, the most restrictive verdict wins, a guard that raises yields DENY (`:324-349`). The full chain is BashGuard, CommandSecurityAnalyzer, ExecApprovalPolicy, financial, outbound and (optionally) egress adapters (`:352-365`); the first three only look at `command` of `bash`/`powershell` (`:41, 79-83`).
5. Mode `shell_guard_mode` (default `enforce`, `weebot/config/settings.py:191-195`): in `enforce` a DENY returns an error and is never approvable (`weebot/application/services/tool_guards.py:423-427`); an ASK, or any ASK marked `enforce_always` by the outbound adapter (`:313-318`), goes to `_resolve_ask` (`:428-434`).
6. `_resolve_ask` skips the question if the executor already approved this exact call (`:447-449`, `weebot/application/services/tool_approval.py:192-194`), else asks `current_approval()` (`weebot/application/services/tool_guards.py:461-462`): `DenyApproval` (process default, `weebot/application/services/tool_approval.py:103-111, 172`), `ConsoleApproval` (TTY prompt, `:135-159`) or `FlowPauseApproval` (answers PENDING, then consumes a single-use grant on retry, `:114-127`). PENDING returns `pending_result` with `data["approval_required"]` (`:246-263`), which the executor turns into `ToolApprovalEvent` + `WaitForUserEvent` (`weebot/application/agents/executor/_base.py:1016-1029`).
7. The LLM sees `str(result)` (`:1041`), fenced when the tool is untrusted (`:1042-1043`). `result.data` goes to the executor's `_facts`, not to the model (`:1007-1008`).

Consequences (read from source, not run):
- Only `output`/`error` reach the model. A tool that puts its payload only in `data` gives the agent nothing to act on; see the WebTools card (`search_images`).
- Retries re-run the whole tool on `OSError`/`ConnectionError` (`weebot/application/models/tool_collection.py:87, 311-323`), including non-idempotent ones like `bash` or `file_editor`.
- `error_result(error, data=...)` puts `data` into `metadata["data"]`, not `data`, because `data` is not a parameter (`weebot/domain/models/tool_result.py:96-108`).

## Connected to
- **Built by** `RoleBasedToolRegistry.create_tool_collection*`, which wraps with `guard_tools(..., include_egress=False)` (`weebot/tools/tool_registry.py:519-521`); `interfaces/factories.py:432-439`, which wraps again after MCP/Apify tools join and fails closed without the guard (`:437-438`); the DI `guard_tools` registration (`weebot/application/di/__init__.py:283-288`); the MCP server, with egress included (`weebot/mcp/server.py:271-274, 388-392`). Empty collections: `cqrs/handlers/execute_step_handler.py:26, 64`, `di/__init__.py:448`.
- **Used by** `ToolExecutor` (above); teardown from `plan_act_flow.py:511`, `agent_session_manager.py:45`, `dispatch_session_input.py:95, 118`.
- **Related:** the ExecTools and WebTools cards (concrete tools), the RoleBasedToolRegistry card, the BashGuard / ExecApprovalPolicy / EgressGuard / ApprovalManager cards, `call_fingerprint` (`weebot/core/approval.py:126`).
- **Looks like but is not:** `weebot/tools/validation.py` (a second, unused validation pipeline; see ExecTools); `ApprovalManager` itself, which only stores grants (`tool_approval.py:93`).

## If you change this
**Hits:** every tool (field defaults, `to_param`), every flow's tool dispatch, the guard decorator, MCP server tools. Tests: `tests/unit/tools/test_base_tool.py`, `tests/unit/tools/test_tool_result_enhanced.py`, `tests/unit/test_tool_collection_retry.py`, `tests/unit/test_tool_health.py`, `tests/unit/test_tool_truncation.py`, `tests/unit/test_parallel_tool_execution.py`, `tests/unit/application/services/test_tool_guards.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/fixes/test_f01_powershell_skips_bash_guard.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/mcp/test_mcp_tool_guards.py`, `tests/unit/tools/test_tool_registry.py`; 50 test files name `ToolCollection`.
**Does not hit:** which role sees a tool (registry table); the rules inside BashGuard / ExecApprovalPolicy.

## Surfaces
Every agent tool call; the approval prompt in the CLI and the web UI pause (`tool_approval.py:227-243`); MCP clients via `run_mcp.py`.

## See
`weebot/domain/models/base_tool.py`, `weebot/application/models/tool_collection.py`, `weebot/application/services/tool_guards.py`
