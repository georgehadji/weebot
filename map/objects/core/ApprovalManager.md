---
type: object
name: ApprovalManager (interactive approval layer)
code: ApprovalManager, ApprovalRequest, ApprovalDecision, console_approval_callback
cluster: core
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# ApprovalManager

The session-scoped store of single-use, 10-minute grants for one exact tool call (ADR-013), plus the call fingerprint and the "a human approved this call" marker the shell tools read (`weebot/core/approval.py:1-7`). The approval strategies that ask a human live in `application/services/tool_approval.py`, not here.

## Why this shape
A grant can only authorise the exact call a human saw: it is keyed on a SHA-256 of the tool name plus canonical JSON arguments, so any changed character gives a new fingerprint (`approval.py:126-133`). There is no "approve the whole session" switch and no way for a DENY verdict to reach the store (`:157-168`). This replaced the earlier prompt-and-cache manager, which approved by raw command string and could approve a BLOCKED command (F07, `:166-168`).

## Shape
- `call_fingerprint(tool_name, arguments)` (`:126-133`); `GRANT_TTL_SECONDS = 600.0` (`:122-123`).
- `ApprovalManager(ttl_seconds, clock, max_sessions=50, on_expired)` (`:171-183`):
  - `grant(session_id, fingerprint)` records an expiry; past 50 sessions the oldest session is evicted (`:185-190`).
  - `consume(session_id, fingerprint)` pops the grant and returns True only if it had not expired; an expired grant calls `on_expired` (`:192-202`).
- `human_approved_call(tool_name)` context manager and `is_human_approved(tool_name)`, a `ContextVar` marker so a shell tool does not refuse a call a human just approved (`:136-154`).
- Older BashGuard-shaped types still in the file: `ApprovalDecision` (`:28-33`), frozen `ApprovalRequest(command, risk_level, checks, session_id, context)` with `format_prompt` / `format_simple` (`:36-116`), `ApprovalCallback` alias (`:119-120`), `console_approval_callback` (Rich panel, plain text on ImportError, `asyncio.to_thread(input, ...)`, EOF or Ctrl-C denies, `:205-303`), and `async` `auto_approve_callback` / `auto_deny_callback` (`:306-334`).

Consequences (read from source, not run):
- One process-wide store: `tool_approval._GRANTS = ApprovalManager(on_expired=_journal_expired)` (`weebot/application/services/tool_approval.py:89-97`). `FlowPauseApproval` consumes a grant to run a resumed call, else returns PENDING (`:114-127`); `record_flow_reply` issues the grant when a human approves (`:304-327`).
- `GuardedTool` runs an approved ASK inside `human_approved_call` (`weebot/application/services/tool_guards.py:431-438`); `bash_tool`, `powershell_tool` and `python_tool` skip their own "requires confirmation" refusal when `is_human_approved` is true (`weebot/tools/bash_tool.py:396`, `weebot/tools/powershell_tool.py:198`, `weebot/tools/python_tool.py:161`).
- `call_fingerprint` is also used by the egress gate in `ToolExecutor` (`weebot/application/agents/executor/_tool_executor.py:52-60, 360-362`).
- `console_approval_callback` and `ApprovalRequest` have no runtime caller: `ConsoleApproval` asks with its own prompt (`tool_approval.py:135-159`); `ApprovalRequest` is used by `examples/phase11/02_bash_safety.py:28` and tests (grep, 2026-10-24). The module docstring says the Console strategy reuses the callback (`approval.py:4-5`); it does not.
- `format_prompt` mixes Rich colour tags into a plain box-drawn string (`:60-73`).

## Connected to
- **Imports** `RiskLevel`, `SafetyCheck` from `weebot/core/bash_guard.py` (`approval.py:23`), used only by the older request/callback types.
- **Owned by** `application/services/tool_approval.py` (the grant store instance and the strategies).
- **Looks like but is not:** `ApprovalMode` in `approval_policy.py` (rule outcome) versus `ApprovalDecision` here (human answer); `ApprovalOutcome` in `application/ports/approval_port.py` (what a strategy returns).

## If you change this
**Hits:** `tool_approval.py` (grants, Flow pause, `record_flow_reply`); `GuardedTool`; the shell and Python tools' confirmation check; the egress and sandbox-network asks in `ToolExecutor` (fingerprint); tests such as `tests/unit/application/services/test_tool_approval.py`, `tests/unit/fixes/test_f07_approval_callbacks.py`, `tests/unit/test_d28_no_blocking_input_in_async.py`.
**Does not hit:** `BashGuard` scoring; `ExecApprovalPolicy` rules; `EgressGuard` classification.

## Surfaces
None directly. Humans see the prompts that `tool_approval.py` builds; the store's grant, use and expiry are journaled by that module.

## See
`weebot/core/approval.py`
