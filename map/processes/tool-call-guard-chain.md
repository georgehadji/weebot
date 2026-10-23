---
type: process
name: tool call guard chain
code: ToolExecutor.execute_tool -> ToolCollection.execute -> GuardedTool.execute
cluster: application
universe: live
status: verified
verified: 2026-10-23
commit: c2f39937
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
**Output:** a `ToolResult`; `str(result)` goes back to the model, fenced when the tool is untrusted; a pending approval becomes `ToolApprovalEvent` + `WaitForUserEvent`.

Line numbers include uncommitted edits to `tool_collection.py` on 2026-10-23.

## Steps
1. **Batch.** The executor collects the response's tool calls (`weebot/application/agents/executor/_base.py:814-837`) and calls `execute_tool_batch`, which runs each call concurrently and keeps order (`weebot/application/agents/executor/_tool_executor.py:223-236`, `_execute_single_tool_call` `:402-406`).
2. **Parse and time out.** `execute_tool` (`_tool_executor.py:240`) parses JSON arguments, repairing once (`:247-279`); timeout is the tool's `default_timeout_seconds`, or the call's `timeout` + 5 s capped at 305 s (`:284-289`); `pre_tool_call` hook (`:290-301`).
3. **Egress gate (ToolExecutor, not the chain).** `guard = self._get_egress_guard()` (`:305`, resolver `:166-198`). No guard and enforcing: a possibly-outbound tool is refused (`:306-319`). Otherwise `EgressGuard.classify` with the session taint flag (`:323-325`; `weebot/core/egress_guard.py:299-345`). `requires_approval` and `is_enforcing()` (`egress_guard.py:41-47`, env `WEEBOT_EGRESS_ENFORCE`, default true) sends the call to `_ask_about_egress` (`_tool_executor.py:326-335`), which asks `tool_approval.current_approval()` (`:42-72`); approval records the call's fingerprint as `approved_call` (`:333-335`). Non-egress network use in a network-off sandbox asks separately (`_clear_network_use`, `:75-122`, called `:342-349`).
4. **Dispatch.** Inside `approval_scope(session_id, approved_call)` and an `asyncio.wait_for` (`_tool_executor.py:353-366`), `ToolCollection.execute(_name, **args)` (`weebot/application/models/tool_collection.py:177`): fuzzy name match on a miss (`:178-182`), canonicalizer (`:199-200`), per-tool semaphore (`:223-238`), retries up to `DEFAULT_MAX_RETRIES` (`:86, 233-243`), output truncation (`:258-260`). A tool hidden by per-step scoping still runs (`:149-156`).
5. **Which tools are wrapped.** `guard_tools` wraps `bash`, `powershell`, `python_execute` (`GUARDED_TOOLS`, `weebot/application/services/tool_guards.py:43`) and every tool matching `is_financial_tool` or `is_outbound_tool` (`:476-498`). `is_outbound_tool` matches `outbound_tool_patterns`, and fails closed for MCP: any `mcp__*` tool whose name does not read as a read verb asks (`:241-257`, verb test `:275-295`). Wrapping happens in the registry (`weebot/tools/tool_registry.py:519-521`) and again in `build_tools` after MCP/extra/Apify tools join, with a `RuntimeError` when no guard is available (`weebot/interfaces/factories.py:432-439`). Both pass `include_egress=False`, because step 3 already gates egress (`tool_guards.py:352-356`).
6. **Chain.** `GuardedTool.execute` (`tool_guards.py:408`) runs `GuardChain.evaluate`: every guard is asked, a guard that raises gives DENY, the most restrictive verdict wins (`:334-349`). `default_guard_chain` order: `BashGuardAdapter` (BLOCKED to DENY, DANGEROUS to ASK, `:89-115`), `AnalyzerAdapter` (`:118`), `ApprovalPolicyAdapter` (not approved to DENY, needs confirmation to ASK; also reads `python_execute`'s `code`, `:152-177`), `FinancialToolAdapter` (`:228-238`), `OutboundToolAdapter` (ASK with `enforce_always` from `outbound_ask_in_observe`, `:298-321`), and `EgressAdapter` only when `include_egress` (`:352-365`). The first three look only at `command` of `bash`/`powershell` (`:41, 79-84`).
7. **Mode.** `shell_guard_mode` (`tool_guards.py:368-371`; field `weebot/config/settings.py:191`). In `enforce`, DENY returns an error result and is never approvable (`tool_guards.py:423-427`). An ASK goes to `_resolve_ask` in `enforce`, or in any mode when an ASK verdict has `enforce_always` (`:428-431`). In `observe` everything else runs unchanged (`:439`).
8. **Approval channel.** `_resolve_ask` (`tool_guards.py:441`) skips the question when this exact call was approved at step 3 (`:447-448`; `weebot/application/services/tool_approval.py:192-195`), else resolves through `self._approval or current_approval()` (`tool_guards.py:461-462`). The channel is the scope's or the process's (`tool_approval.py:172-189`): `DenyApproval` by default (`:103-111, 172`), `ConsoleApproval` installed by the CLI on a TTY (`:135-159`; `cli/commands/flow.py:51-56`), `FlowPauseApproval` installed by the web app (`tool_approval.py:114-127`; `weebot/interfaces/web/main.py:201`), and `DenyApproval` again inside the webhook and cron scopes (`weebot/interfaces/web/routers/webhook.py:146`, `weebot/application/services/cron_agent_runner.py:67`). APPROVED runs the call; PENDING returns `pending_result` (`tool_guards.py:465-466`, `tool_approval.py:246-263`); DENIED returns `denied_result` (`tool_guards.py:467`, `tool_approval.py:266`).
9. **human_approved_call.** An approved ASK runs the inner tool inside `human_approved_call(name)` (`tool_guards.py:435-438`; `weebot/core/approval.py:139-154`), which lets the shell tools skip their own confirmation gate (`weebot/tools/bash_tool.py:396`, `weebot/tools/powershell_tool.py:198`, `weebot/tools/python_tool.py:161`).
10. **After the call.** Timeout gives an error result (`_tool_executor.py:367-374`); `post_tool_call` hook (`:377-390`); a successful call of a tool that `taints_egress_context` sets `_untrusted_context_active` (`:398-399`; `weebot/core/trust_boundary.py:160-167`).
11. **Back in the executor.** `result.data` goes to `_facts` (`_base.py:1005`); `approval_required` in `data` yields `ToolApprovalEvent` then `WaitForUserEvent` and ends the step (`:1013-1027`); the model receives `str(result)`, wrapped by `wrap_untrusted` when `is_untrusted_tool` (`:1038-1043`; `trust_boundary.py:98, 141`). On resume, `FlowRouter` turns the reply into a single-use grant through `record_flow_reply` (`weebot/application/flows/flow_router.py:124-150`; `tool_approval.py:304-327`), which `FlowPauseApproval` consumes on retry (`:120-127`).

Consequences (read from source, not run):
- The taint flag does not outlive a step. It lives on the `ToolExecutor` (`_tool_executor.py:149-152`), built inside each `ExecutorAgent` (`_base.py:322-329`), and `ExecuteStepHandler` builds a new `ExecutorAgent` for every step (`weebot/application/di/__init__.py:464`; `weebot/application/cqrs/handlers/execute_step_handler.py:97-101`). Content fetched in step N does not gate egress to a known recipient in step N+1, though the comment calls the taint sticky for the session (`_tool_executor.py:392-397`).
- MCP tool errors read as success: `MCPToolAdapter.execute` returns `success=True` with whatever text `call_tool` joined, and `call_tool` never checks the MCP result's error flag (`weebot/infrastructure/mcp/mcp_toolkit_adapter.py:20-25`; `weebot/infrastructure/mcp/mcp_client_manager.py:255-267`).
- A model can set `_max_retries` in its own arguments: `ToolCollection.execute` pops it from the call kwargs (`tool_collection.py:233`).
- The module docstring still says `observe` is the default (`tool_guards.py:13`); the setting defaults to `enforce` (`settings.py:191`).

## If you change this
**Hits:** every guarded tool call in flows and the MCP server; the CLI approval prompt and web pause; `bash_tool` / `powershell_tool` / `python_tool` confirmation gates; tests `tests/unit/application/services/test_tool_guards.py`, `tests/unit/application/services/test_tool_approval.py`, `tests/unit/test_executor_tool_approval_pause.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/fixes/test_f06_financial_tools_ask.py`, `tests/unit/mcp/test_mcp_tool_guards.py`.
**Does not hit:** the rules inside `BashGuard`, `CommandSecurityAnalyzer`, `ExecApprovalPolicy`, `EgressGuard` (the adapters only translate their results); which role sees a tool (`RoleBasedToolRegistry`).

## See
`weebot/application/services/tool_guards.py`, `weebot/application/services/tool_approval.py`, `weebot/application/agents/executor/_tool_executor.py`
