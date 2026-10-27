---
type: process
name: tool call guard chain
code: ToolExecutor.execute_tool -> ToolCollection.execute -> GuardedTool.execute
cluster: application
universe: live
status: verified
verified: 2026-10-27
commit: 7d1ce324
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
1. **Batch.** The step loop hands the response's tool calls to `ToolBatchRunner.run` (`weebot/application/agents/executor/_base.py:616-622`), which calls `execute_tool_batch` (`weebot/application/agents/executor/_tool_batch.py:117`). That runs each call concurrently and keeps order (`weebot/application/agents/executor/_tool_executor.py:318-331`, `_execute_single_tool_call` `:560-564`).
2. **Parse and time out.** `execute_tool` (`_tool_executor.py:335`) parses JSON arguments, repairing once (`:337-369`), replays the session's persisted flags once (`:373`); timeout is the tool's `default_timeout_seconds`, or the call's `timeout` + 5 s capped at 305 s (`:376-380`); `pre_tool_call` hook (`:383-392`).
3. **Egress gate (ToolExecutor, not the chain).** `guard = self._get_egress_guard()` (`:397`, resolver `:256-288`). No guard and enforcing: a possibly-outbound tool is refused (`:398-411`, name test `:290-309`). Otherwise `EgressGuard.classify` with the session taint flag (`:415-418`; `weebot/core/egress_guard.py:373-420`). An egress this session already completed is not repeated and never reaches approval (`:422-434`). `requires_approval` and `is_enforcing()` (`egress_guard.py:43-49`, env `WEEBOT_EGRESS_ENFORCE`, default true) sends the call to `_ask_about_egress` (`_tool_executor.py:47-77`, called `:436-442`), which asks `tool_approval.current_approval()`; approval records the call's fingerprint as `approved_call` (`:443-445`). Detect-only mode logs and lets it through (`:446-449`). Non-egress network use in a network-off sandbox asks separately (`_clear_network_use`, `:80-124`, called `:453-458`).
4. **Dispatch.** Inside `approval_scope(session_id, approved_call)` and an `asyncio.wait_for` (`_tool_executor.py:467-481`), `ToolCollection.execute(_name, **args)` (`weebot/application/models/tool_collection.py:195`): fuzzy name match on a miss (`:196-200`), unhealthy tools refused (`:206-214`), canonicalizer (`:216-226`), result cache (`:232-238`), per-tool semaphore (`:240-247`), retries up to `DEFAULT_MAX_RETRIES` on transient errors (`:86, 253, 303-341`), output truncation (`:275-285`). A tool hidden by per-step scoping still runs (`:167-169`).
5. **Which tools are wrapped.** `guard_tools` wraps `bash`, `powershell`, `python_execute` (`GUARDED_TOOLS`, `weebot/application/services/tool_guards.py:43`) and every tool matching `is_financial_tool` or `is_outbound_tool` (`:481-502`). `is_outbound_tool` matches `outbound_tool_patterns`, and fails closed for MCP: any `mcp__*` tool whose name does not read as a read verb asks (`:241-257`, verb test `:260-295`). Wrapping happens in the registry (`weebot/application/services/tool_registry.py:532-534`) and again in `build_tools` after MCP/extra/Apify tools join, with a `RuntimeError` when no guard is available (`weebot/interfaces/factories.py:352-359`). Both pass `include_egress=False`, because step 3 already gates egress (`tool_guards.py:378-381`).
6. **Chain.** `GuardedTool.execute` (`tool_guards.py:439`) runs `GuardChain.evaluate`: every guard is asked, a guard that raises gives DENY, the most restrictive verdict wins (`:334-349`). `default_guard_chain` order: `BashGuardAdapter` (BLOCKED to DENY, DANGEROUS to ASK, `:89-115`), `AnalyzerAdapter` (DANGEROUS to DENY, `:118-149`), `ApprovalPolicyAdapter` (not approved to DENY, needs confirmation to ASK, `:152-177`), `FinancialToolAdapter` (`:228-238`), `OutboundToolAdapter` (ASK with `enforce_always` from `outbound_ask_in_observe`, `:298-318`), and `EgressAdapter` only when `include_egress` (`:180-205, 363-364`). The first two look only at `command` of `bash`/`powershell` (`:41, 79-83`); the third also reads `python_execute`'s `code` (`:166-167`).
7. **Mode.** `shell_guard_mode` (`tool_guards.py:394-397`; field `weebot/config/settings.py:208-212`, default `enforce`). In `enforce`, DENY returns an error result and is never approvable (`tool_guards.py:454-458`). An ASK goes to `_resolve_ask` in `enforce`, or in any mode when an ASK verdict has `enforce_always` (`:433-437`). In `observe` everything else runs unchanged (`:444`).
8. **Approval channel.** `_resolve_ask` (`tool_guards.py:472`) skips the question when this exact call was approved at step 3 (`:453-454`; `weebot/application/services/tool_approval.py:192-194`), else resolves through `self._approval or current_approval()` (`tool_guards.py:492-493`). The channel is the scope's or the process's (`tool_approval.py:172, 184-185`): `DenyApproval` by default (`:103-111, 172`), `ConsoleApproval` installed by the CLI on a TTY (`:135-159`; `cli/commands/flow.py:44-53`), `FlowPauseApproval` installed by the web app (`tool_approval.py:114-127`; `weebot/interfaces/web/main.py:202`), and `DenyApproval` again inside the webhook and cron scopes (`weebot/interfaces/web/routers/webhook.py:146`, `weebot/application/services/cron_agent_runner.py:67`). APPROVED runs the call; PENDING returns `pending_result` (`tool_guards.py:496-497`, `tool_approval.py:246-263`); DENIED returns `denied_result` (`tool_guards.py:498`, `tool_approval.py:266`).
9. **human_approved_call.** An approved ASK runs the inner tool inside `human_approved_call(name)` (`tool_guards.py:466-469`; `weebot/core/approval.py:142-149`), which lets the shell tools skip their own confirmation gate (`weebot/tools/bash_tool.py:398`, `weebot/tools/powershell_tool.py:193`, `weebot/tools/python_tool.py:166`).
10. **After the call.** Timeout gives an error result (`_tool_executor.py:482-489`); a completed egress is recorded in the effect ledger (`:487-497`); `post_tool_call` hook (`:499-512`); a successful call whose tool's declared trust is EXTERNAL sets `_untrusted_context_active`, except a local browser tab or a file this session wrote (`:524-546`; `weebot/core/trust_boundary.py:79-90`).
11. **Back in the executor.** `result.data` goes to `_facts` (`_tool_batch.py:209-210`); `approval_required` in `data` yields `ToolApprovalEvent` then `WaitForUserEvent` and ends the step (`_tool_batch.py:211-215`; `weebot/application/agents/executor/_step_result_handler.py:16-41`); the model receives `str(result)`, wrapped by `wrap_untrusted` unless the tool is LOCAL (`_tool_batch.py:229`; `_base.py:327-348`; `trust_boundary.py:74-76, 107`). On resume, `FlowRouter` turns the reply into a single-use grant through `record_flow_reply` (`weebot/application/flows/flow_router.py:144-149`; `tool_approval.py:304-327`), which `FlowPauseApproval` consumes on retry (`:124-126`).

Consequences (read from source, not run):
- The taint flag outlives a step. The executor reads it from a process-wide `SessionScope` keyed by session id (`_tool_executor.py:176, 184-193`; `weebot/application/agents/executor/_session_scope.py:31-59, 136-138`), the write is also appended as a `session_flag` row and replayed on a new process (`_tool_executor.py:205-217, 224-236`). It is dropped only by `close`, called when a session completes or is deleted (`_session_scope.py:99-111`; `weebot/application/flows/states/completed.py:301`; `weebot/interfaces/web/routers/sessions.py:220`), and the module says never to put a TTL on it (`_session_scope.py:18-21`).
- Taint comes only from a non-error result of an EXTERNAL tool (`trust_boundary.py:79-90`). A `file://` or loopback tab and the session's own written files do not taint (`_tool_executor.py:529-551`); the tab state is tracked from the last navigate, not the real tab (`:522-523`).

## If you change this
**Hits:** every guarded tool call in flows and the MCP server; the CLI approval prompt and web pause; `bash_tool` / `powershell_tool` / `python_tool` confirmation gates; tests `tests/unit/application/services/test_tool_guards.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/mcp/test_mcp_tool_guards.py`.
**Does not hit:** the rules inside `BashGuard`, `CommandSecurityAnalyzer`, `ExecApprovalPolicy`, `EgressGuard` (the adapters only translate their results); which role sees a tool (`RoleBasedToolRegistry`).

## See
`weebot/application/services/tool_guards.py`, `weebot/application/services/tool_approval.py`, `weebot/application/agents/executor/_tool_executor.py`
