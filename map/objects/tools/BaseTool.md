---
type: object
name: BaseTool
code: BaseTool, ToolResult, ToolCollection
cluster: tools
universe: live
status: verified
verified: 2026-10-31
commit: f238f23a
---

# BaseTool

The tool contract. `BaseTool` is what every agent tool subclasses, `ToolResult` is what every tool returns, and `ToolCollection` holds a session's tools and dispatches a call by name. Guards and approval sit between the collection and the tool as a decorator, `GuardedTool`.

## Why this shape
`BaseTool` and `ToolResult` live in the domain layer so ports and application services can name them without importing `weebot/tools/` (`weebot/domain/models/base_tool.py:1-10`, `weebot/domain/models/tool_result.py:1-7`). `weebot/tools/base.py` only re-exports them; `ToolCollection` is re-exported lazily through a module `__getattr__` to avoid an import cycle (`weebot/tools/base.py:11-27`). Guards are a decorator over a tool, not a step inside each tool, so one chain covers the shell tools, the MCP server and MCP-sourced tools (`weebot/application/services/tool_guards.py:1-23`).

## Shape
- `BaseTool(ABC, BaseModel)` (`weebot/domain/models/base_tool.py:22`): fields `name`, `description`, `parameters` (JSON Schema) (`base_tool.py:33-35`); `max_concurrent` (0 = unlimited) (`base_tool.py:41`), `default_timeout_seconds` = 60 (`base_tool.py:44`), `truncation_strategy` = `"head"` (`base_tool.py:48`). `output_trust` is a `ClassVar[OutputTrust]` defaulting to `EXTERNAL`, so an undeclared tool is fenced and tainting; `resolved_output_trust()` lets a wrapper delegate (`base_tool.py:50-57`; enum in `weebot/domain/models/output_trust.py:18-33`, decisions in `weebot/core/trust_boundary.py:58-104`). Abstract `async execute(**kwargs) -> ToolResult` (`base_tool.py:59-61`); `health_check()` defaults to True (`base_tool.py:63-69`); `close()` is a no-op (`base_tool.py:71-81`); `to_param()` builds the OpenAI function spec (`base_tool.py:83-92`). Which roles get a tool is not a field: see the RoleBasedToolRegistry card (`base_tool.py:36-37`).
- `ToolResult` dataclass (`weebot/domain/models/tool_result.py:16`): `output`, `error`, `base64_image`, `success`, `data`, `metadata` (`tool_result.py:33-40`). `__post_init__` keeps `error` and `success` consistent both ways (`tool_result.py:42-50`). `str(result)` is `output`, or `"ERROR: <error>"` (`tool_result.py:57-60`). Factories `success_result(output, data, **metadata)` and `error_result(error, output, **metadata)` (`tool_result.py:78-108`).
- `ToolCollection` (`weebot/application/models/tool_collection.py:82`): a dict keyed by `BaseTool.name` (`tool_collection.py:92`), with optional canonicalizer, contract loader and result cache (`tool_collection.py:89-100`).
  - `set_visible(names)` limits which definitions are sent while every tool stays callable; `hidden_names()` lists the rest (`tool_collection.py:167-174`).
  - `to_params()` skips hidden tools and tools that failed `check_health()` once it has run, and lets the contract loader extend descriptions (`tool_collection.py:176-193`).
  - `canonical_args(name, args)` returns the arguments as `execute` will run them; the executor's effect ledger keys on it (`tool_collection.py:112-128`).
  - `resolve_name(name)` (`tool_collection.py:195`): exact name, else fuzzy match; the executor calls it once, before any guard, so checks and dispatch see the same tool (audit R24).
  - `execute(_name, **kwargs)` (`tool_collection.py:205`): canonical names only, an unknown one is an error (`tool_collection.py:206-210`); refuse an unhealthy tool (`tool_collection.py:212-220`); canonicalizer may block or rewrite args (`tool_collection.py:222-232`); cache lookup (`tool_collection.py:238-244`); per-tool semaphore when `max_concurrent > 0` (`tool_collection.py:246-253`); a model-supplied `_max_retries` is dropped (`tool_collection.py:258`); run; stamp `execution_time_ms`, `retry_count`, `tool_name` (`tool_collection.py:271-279`); truncate output over `MAX_TOOL_OUTPUT_CHARS` (20 000, `weebot/config/constants.py:85`) by the tool's strategy (`weebot/application/models/tool_collection.py:281-291`, `_truncate` `tool_collection.py:23-52`); cache store on success (`tool_collection.py:303-305`).
  - Exceptions: logged with traceback (`tool_collection.py:311`); non-retryable ones return an error result at once (`tool_collection.py:313-323`); `OSError`, `TimeoutError`, `ConnectionError` retry up to `DEFAULT_MAX_RETRIES` = 2 with capped backoff (`tool_collection.py:86-87, 335-347`).
  - `teardown()` shuts down an `apify_service` attribute (looking through a `GuardedTool` to `.inner`) and calls every tool's `close()` (`tool_collection.py:130-154`).

### How a call reaches a tool
1. `ToolExecutor.execute_tool` (`weebot/application/agents/executor/_tool_executor.py:372-619`) takes the timeout from the tool's `default_timeout_seconds` (`_tool_executor.py:424-428`), gets the egress guard (`_tool_executor.py:445`, `_get_egress_guard` `_tool_executor.py:298-330`), runs `guard.classify` (`_tool_executor.py:464-466`) and, if a human approved there, records that call's fingerprint (`_tool_executor.py:489-498`). An egress this session already completed is not re-run: the ledger returns a replay note (`_tool_executor.py:470-488`). After untrusted content, a call that does more than read asks as well (`_tool_executor.py:513-529`).
2. It calls `self._tools.execute(...)` under `approval_scope(session_id, approved_call)` with an `asyncio.wait_for` timeout (`_tool_executor.py:541-547`).
3. `ToolCollection.execute` dispatches to the tool, which for `bash`, `powershell`, `python_execute` and any financial or outbound tool is a `GuardedTool` (`weebot/application/services/tool_guards.py:43, 560-581`).
4. `GuardedTool.execute` (`tool_guards.py:492-523`) runs `GuardChain.evaluate`: every guard is asked, the most restrictive verdict wins, a guard that raises yields DENY (`tool_guards.py:403-428`). The full chain is BashGuard, CommandSecurityAnalyzer, ExecApprovalPolicy, financial, outbound and (optionally) egress adapters (`tool_guards.py:431-444`); the first three only look at `command` of `bash`/`powershell` (`tool_guards.py:41, 79-83`).
5. Mode `shell_guard_mode` (default `enforce`, `weebot/config/settings.py:248-252`): in `enforce` a DENY returns an error and is never approvable (`weebot/application/services/tool_guards.py:507-511`); an ASK, or any ASK marked `enforce_always` by the outbound adapter (`tool_guards.py:350`), goes to `_resolve_ask` (`tool_guards.py:512-522`, `tool_guards.py:525-551`).
6. `_resolve_ask` skips the question if the executor already approved this exact call (`tool_guards.py:532-533`, `weebot/application/services/tool_approval.py:193-195`), else asks `current_approval()` (`weebot/application/services/tool_guards.py:545`): `DenyApproval` (process default, `weebot/application/services/tool_approval.py:104-112, 173`), `ConsoleApproval` (TTY prompt, `tool_approval.py:136-160`) or `FlowPauseApproval` (answers PENDING, then consumes a single-use grant on retry, `tool_approval.py:115-128`). PENDING returns `pending_result` with `data["approval_required"]` (`tool_approval.py:280-297`), which the executor turns into `ToolApprovalEvent` + `WaitForUserEvent` (`weebot/application/agents/executor/_step_result_handler.py:16-41`, called at `weebot/application/agents/executor/_tool_batch.py:224`).
7. The LLM sees `str(result)`, fenced unless the tool's `OutputTrust` is `LOCAL` (`weebot/application/agents/executor/_base.py:252-273`, called at `weebot/application/agents/executor/_tool_batch.py:242`); a non-error `EXTERNAL` result also taints the session (`_tool_executor.py:585-618`). `result.data` goes to the executor's `_facts`, not to the model (`weebot/application/agents/executor/_tool_batch.py:223`).

Consequences (read from source, not run):
- Only `output`/`error` reach the model. A tool that puts its payload only in `data` gives the agent nothing to act on; see the WebTools card (`search_images`).
- Retries re-run the whole tool on `OSError`/`ConnectionError` (`weebot/application/models/tool_collection.py:87, 335-347`), including non-idempotent ones like `bash` or `file_editor`.
- `error_result(error, data=...)` puts `data` into `metadata["data"]`, not `data`, because `data` is not a parameter (`weebot/domain/models/tool_result.py:95-108`).

## Connected to
- **Built by** `RoleBasedToolRegistry.create_tool_collection*`, which wraps with `guard_tools(..., include_egress=False)` (`weebot/application/services/tool_registry.py:543-545`); `interfaces/factories.py:322-398`, which wraps again after MCP/Apify tools join and fails closed without the guard (`interfaces/factories.py:388-395`); the DI `guard_tools` registration (`weebot/application/di/__init__.py:298-303`); the MCP server, with egress included (`weebot/mcp/server.py:269-276, 388-392`). Empty collections: `cqrs/handlers/execute_step_handler.py:26, 69`, `di/__init__.py:490`.
- **Used by** `ToolExecutor` (above); teardown from `plan_act_flow.py:289`, `agent_session_manager.py:45`, `dispatch_session_input.py:114, 140`.
- **Related:** the ExecTools and WebTools cards (concrete tools), the RoleBasedToolRegistry card, the BashGuard / ExecApprovalPolicy / EgressGuard / ApprovalManager cards, `call_fingerprint` (`weebot/core/approval.py:126`).
- **Looks like but is not:** `ApprovalManager` itself, which only stores grants (`tool_approval.py:94`).

## If you change this
**Hits:** every tool (field defaults, `to_param`), every flow's tool dispatch, the guard decorator, MCP server tools. Tests: `tests/unit/tools/test_base_tool.py`, `tests/unit/tools/test_tool_result_enhanced.py`, `tests/unit/test_tool_collection_retry.py`, `tests/unit/test_tool_health.py`, `tests/unit/test_tool_truncation.py`, `tests/unit/test_parallel_tool_execution.py`, `tests/unit/application/services/test_tool_guards.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/fixes/test_f01_powershell_skips_bash_guard.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/mcp/test_mcp_tool_guards.py`, `tests/unit/tools/test_tool_registry.py`; 70 test files name `ToolCollection` (grep, 2026-10-30).
**Does not hit:** which role sees a tool (registry table); the rules inside BashGuard / ExecApprovalPolicy.

## Surfaces
Every agent tool call; the approval prompt in the CLI and the web UI pause, which shows every argument, redacted, with both ends of anything long (`tool_approval.py:243-277`, audit R15); MCP clients via `run_mcp.py`.

## See
`weebot/domain/models/base_tool.py`, `weebot/application/models/tool_collection.py`, `weebot/application/services/tool_guards.py`
