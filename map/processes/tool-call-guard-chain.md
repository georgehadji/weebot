---
type: process
name: tool call guard chain
code: ToolExecutor.execute_tool -> ToolCollection.execute -> GuardedTool.execute
cluster: application
universe: live
status: verified
verified: 2026-10-31
commit: 5fae5eb2
consumes:
  - ../objects/application/ExecutorAgent.md
  - ../objects/tools/BaseTool.md
  - ../objects/core/EgressGuard.md
  - ../objects/core/BashGuard.md
  - ../objects/core/CommandSecurityAnalyzer.md
  - ../objects/core/ExecApprovalPolicy.md
  - ../objects/core/ApprovalManager.md
  - ../objects/core/WeebotSettings.md
  - ../objects/tools/ExecTools.md
  - ../objects/tools/IntegrationTools.md
produces:
  - ../objects/domain/Event.md
  - ../objects/tools/BaseTool.md
---

# tool call guard chain

**Input:** one tool call (`{"function": {"name", "arguments"}}`) in an LLM response inside `ExecutorAgent.execute_step`.
**Movement:** `ToolExecutor` parses it and runs the egress gate; `ToolCollection.execute` dispatches by name; a `GuardedTool` runs the guard chain and, on ASK, the approval channel; the inner tool runs, under `human_approved_call` when a human said yes.
**Output:** a `ToolResult`; `str(result)` goes back to the model, fenced when the tool is not LOCAL; a pending approval becomes `ToolApprovalEvent` + `WaitForUserEvent`.

## Steps
1. **Batch.** The step loop hands the response's tool calls to `ToolBatchRunner.run` (`weebot/application/agents/executor/_base.py:549-555`), which calls `execute_tool_batch` (`weebot/application/agents/executor/_tool_batch.py:130`). That runs each call concurrently and keeps order (`weebot/application/agents/executor/_tool_executor.py:355-368`, `_execute_single_tool_call` `:631-635`).
2. **Parse and time out.** `execute_tool` (`_tool_executor.py:372`) parses JSON arguments, repairing once (`:379-413`), resolves the tool name once before any check (`ToolCollection.resolve_name`, `:415-419`; `weebot/application/models/tool_collection.py:195-203`), replays the session's persisted flags once (`:421`); timeout is the tool's `default_timeout_seconds`, or the call's `timeout` + 5 s capped at 305 s (`:423-428`); `pre_tool_call` hook (`:430-440`).
3. **Egress gate (ToolExecutor, not the chain).** `guard = self._get_egress_guard()` (`:445`, resolver `:298-330`). No guard and enforcing: a possibly-outbound tool is refused (`:446-459`, name test `:332-351`). Otherwise `EgressGuard.classify` with the session taint flag (`:463-466`; `weebot/core/egress_guard.py:388-438`). An egress this session already completed is not repeated and never reaches approval (`:467-488`). `requires_approval` and `is_enforcing()` (`egress_guard.py:44-50`, env `WEEBOT_EGRESS_ENFORCE`, default true) sends the call to `_ask_about_egress` (`_tool_executor.py:48-78`, called `:489-495`), which asks `tool_approval.current_approval()`; approval records the call's fingerprint as `approved_call` (`:496-498`). Detect-only mode logs and lets it through (`:499-502`). Non-egress network use in a network-off sandbox asks separately (`_clear_network_use`, `:105-154`, called `:505-511`).
   After untrusted content (decision D5): when the session is tainted and no approval was given above, a call for which `reads_only` (`weebot/application/services/tool_guards.py:375-397`) is false asks through `_ask_after_untrusted_content` (`_tool_executor.py:81-102`, called `:513-529`); outside `enforce` mode it only logs (`:519-520`).
4. **Dispatch.** Inside `approval_scope(session_id, approved_call)` and an `asyncio.wait_for` (`_tool_executor.py:541-547`), `ToolCollection.execute(_name, **args)` (`weebot/application/models/tool_collection.py:205`): unknown name refused (`:206-210`; the fuzzy match moved to `resolve_name`, step 2), unhealthy tools refused (`:213-220`), canonicalizer (`:222-232`), result cache (`:238-244`), per-tool semaphore (`:246-253`), retries up to `DEFAULT_MAX_RETRIES` on transient errors (`:86, 259, 309-347`), output truncation (`:281-291`). A tool hidden by per-step scoping still runs (`:167-169`).
5. **Which tools are wrapped.** `guard_tools` wraps `bash`, `powershell`, `python_execute` (`GUARDED_TOOLS`, `weebot/application/services/tool_guards.py:43`) and every tool matching `is_financial_tool` or `is_outbound_tool` (`:560-581`). `is_outbound_tool` matches `outbound_tool_patterns`, and fails closed for MCP: any `mcp__*` tool whose name does not read as a read verb asks (`:274-290`, verb test `:293-328`). Wrapping happens in the registry (`weebot/application/services/tool_registry.py:539-541`) and again in `build_tools` after MCP/extra/Apify tools join, with a `RuntimeError` when no guard is available (`weebot/interfaces/factories.py:388-395`). Both pass `include_egress=False`, because step 3 already gates egress (`tool_guards.py:431-434`).
6. **Chain.** `GuardedTool.execute` (`tool_guards.py:492`) runs `GuardChain.evaluate`: every guard is asked, a guard that raises gives DENY, the most restrictive verdict wins (`:413-428`). `default_guard_chain` order (`:431-444`): `BashGuardAdapter` (BLOCKED to DENY, DANGEROUS to ASK, `:89-115`), `AnalyzerAdapter` (DANGEROUS to DENY, `:118-149`), `ApprovalPolicyAdapter` (not approved to DENY, needs confirmation to ASK, `:152-182`; a shell segment no rule covers can also ask, `_default_ask`, `:184-207`, setting `shell_default_ask`), `FinancialToolAdapter` (`:261-271`), `OutboundToolAdapter` (ASK with `enforce_always` from `outbound_ask_in_observe`, `:331-351`), and `EgressAdapter` only when `include_egress` (`:210-238, 442-443`). The first two look only at `command` of `bash`/`powershell` (`:41, 79-83`); the third also reads `python_execute`'s `code` (`:169-171`).
7. **Mode.** `shell_guard_mode` (`tool_guards.py:447-450`; field `weebot/config/settings.py:224-228`, default `enforce`). In `enforce`, DENY returns an error result and is never approvable (`tool_guards.py:507-511`). An ASK goes to `_resolve_ask` in `enforce`, or in any mode when an ASK verdict has `enforce_always` (`:512-516`). In `observe` everything else runs unchanged (`:523`).
8. **Approval channel.** `_resolve_ask` (`tool_guards.py:525`) skips the question when this exact call was approved at step 3 (`:531-533`; `weebot/application/services/tool_approval.py:193-195`), else resolves through `self._approval or current_approval()` (`tool_guards.py:545`). The channel is the scope's or the process's (`tool_approval.py:173-186`): `DenyApproval` by default (`:104-112, 173`), `ConsoleApproval` installed by the CLI on a TTY (`:136-160`; `cli/commands/flow.py:44-53`), `FlowPauseApproval` installed by the web app (`tool_approval.py:115-128`; `weebot/interfaces/web/main.py:203`), and `DenyApproval` again inside the webhook and cron scopes (`weebot/interfaces/web/routers/webhook.py:139`, `weebot/application/services/cron_agent_runner.py:67`). APPROVED runs the call; PENDING returns `pending_result` (`tool_guards.py:549-550`, `tool_approval.py:280-297`); DENIED returns `denied_result` (`tool_guards.py:551`, `tool_approval.py:300`).
9. **human_approved_call.** An approved ASK runs the inner tool inside `human_approved_call(name)` (`tool_guards.py:519-522`; `weebot/core/approval.py:142-149`), which lets the shell tools skip their own confirmation gate (`weebot/tools/bash_tool.py:400`, `weebot/tools/powershell_tool.py:165`, `weebot/tools/python_tool.py:170`).
10. **After the call.** Timeout gives an error result (`_tool_executor.py:548-555`); a completed egress is recorded in the effect ledger (`:558-568`); `post_tool_call` hook (`:570-583`); a successful call whose tool's declared trust is EXTERNAL sets `_untrusted_context_active`, except a local browser tab or a file this session wrote (`:585-617`; `weebot/core/trust_boundary.py:79-90`).
11. **Back in the executor.** `result.data` goes to `_facts` (`_tool_batch.py:222-223`); `approval_required` in `data` yields `ToolApprovalEvent` then `WaitForUserEvent` and ends the step (`_tool_batch.py:224-228`; `weebot/application/agents/executor/_step_result_handler.py:16-41`); the model receives `str(result)`, wrapped by `wrap_untrusted` unless the tool is LOCAL (`_tool_batch.py:242`; `_base.py:252-273`; `trust_boundary.py:74-76, 107`). On resume, `FlowRouter` turns the reply into a single-use grant through `record_flow_reply` (`weebot/application/flows/flow_router.py:144-149`; `tool_approval.py:338-361`), which `FlowPauseApproval` consumes on retry (`:125-127`).

Consequences (read from source, not run):
- The taint flag outlives a step. The executor reads it from a process-wide `SessionScope` keyed by session id (`_tool_executor.py:209-218`; `weebot/application/agents/executor/_session_scope.py:33-65`), the write is also appended as a `session_flag` row and replayed on a new process (`_tool_executor.py:230-242, 254-278`). It is dropped only by `close`, called when a session completes or is deleted (`_session_scope.py:125-137`; `weebot/application/flows/states/completed.py:326`; `weebot/application/use_cases/delete_session.py:39`, after the run is stopped (audit R04)), and the module says never to put a TTL on it (`_session_scope.py:18-21`).
- Taint comes only from a non-error result of an EXTERNAL tool (`trust_boundary.py:79-90`). A `file://` or loopback tab and the session's own written files do not taint (`_tool_executor.py:595-616`); the tab state is tracked from the last navigate, not the real tab (`:592-594`).

## If you change this
**Hits:** every guarded tool call in flows and the MCP server; the CLI approval prompt and web pause; `bash_tool` / `powershell_tool` / `python_tool` confirmation gates; tests `tests/unit/application/services/test_tool_guards.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/mcp/test_mcp_tool_guards.py`.
**Does not hit:** the rules inside `BashGuard`, `CommandSecurityAnalyzer`, `ExecApprovalPolicy`, `EgressGuard` (the adapters only translate their results); which role sees a tool (`RoleBasedToolRegistry`).

## See
`weebot/application/services/tool_guards.py`, `weebot/application/services/tool_approval.py`, `weebot/application/agents/executor/_tool_executor.py`
