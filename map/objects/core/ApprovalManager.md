---
type: object
name: ApprovalManager (interactive approval layer)
code: ApprovalManager, ApprovalRequest, ApprovalDecision, console_approval_callback
cluster: core
universe: live
status: stale
verified: 2026-10-21
commit: f00ea38
---

# ApprovalManager

**Stale since 2026-10-22 (plan W3.4, ADR-013).** `ApprovalManager` is now the session-scoped store of single-use, 10-minute tool-call grants keyed by `call_fingerprint()`. The prompt-and-cache API described below was deleted. The live callers are `application/services/tool_approval.py` (strategies, `record_flow_reply`), `GuardedTool` and the egress gate in `ToolExecutor`. The text below describes `f00ea38`; re-verify before relying on it.

At `f00ea38`: an approval workflow for commands that `BashGuard` rated SUSPICIOUS or DANGEROUS. It auto-approved SAFE, auto-denied BLOCKED, remembered per-session decisions, and otherwise asked a callback. It was complete and tested, and nothing in the running system used it.

## Why this shape
Written to turn `BashGuard.requires_approval()` into an actual decision point (`weebot/core/approval.py:1-5`). It is fail-closed: no callback means DENIED, and a callback that raises means DENIED (`:204-217`). The universe is `ghost`: do not build new features on it before deciding whether to wire it (see "Consequences").

## Shape
- `ApprovalDecision`: approved, denied, deferred (`:20-25`). `ApprovalRequest(command, risk_level, checks, session_id, context)` is a frozen dataclass with two text formatters (`:28-108`).
- `ApprovalManager.request_approval` (`:165-217`), in order: SAFE approved (`:181`); BLOCKED denied when `auto_deny_blocked` (`:186`); a cached session decision (`:193-196`); a per-session command whitelist (`:199-202`); the callback (`:205-213`); no callback denies (`:215-217`).
- Session state: `_session_approvals` is capped at 50 and evicts the oldest (`:152, 228-236`); `_session_whitelist` is only removed together with it (`:235`, `:239-250`).
- Callbacks: `console_approval_callback` prints a Rich panel (plain text on ImportError) and reads the answer with `asyncio.to_thread(input, ...)` so the event loop is not blocked (`:285-383`); EOF or Ctrl-C denies. `auto_approve_callback` and `auto_deny_callback` (`:386-414`). A module-level `default_approval_manager` exists (`:282`).

Consequences (read from source, not run):
- **No runtime caller.** Importers are `examples/phase11/02_bash_safety.py:28,117` and `tests/unit/test_d28_no_blocking_input_in_async.py:37` (grep, 2026-10-21). `default_approval_manager` has no user. The shell tools return "requires confirmation" as an error string instead (see the ExecApprovalPolicy card), so DANGEROUS has no approval path at all.
- Fixed 2026-10-22 (W1.2): `auto_approve_callback` and `auto_deny_callback` were plain `def` and so always denied when awaited; they are `async def` now. `format_prompt`'s two lines without the `f` prefix are fixed. It still mixes Rich colour tags into a plain box, and nothing calls it (grep).
- With `auto_deny_blocked=False`, a session-level APPROVED applies to BLOCKED commands too, because the session check follows the BLOCKED check (`:186-196`).
- `console_approval_callback` has no lock; two concurrent requests would interleave prompts on one stdin.

## Connected to
- **Imports** `RiskLevel`, `SafetyCheck` from `weebot/core/bash_guard.py:15`, so it is keyed to BashGuard's four levels, not to `ExecApprovalPolicy`'s modes.
- **Related:** `BashGuard` (produces the request), `ExecApprovalPolicy` (the gate that is actually enforced).
- **Looks like but is not:** `ApprovalMode` in `approval_policy.py` (rule outcome) versus `ApprovalDecision` here (human answer); the inbound-mail pause in `FlowRouter` (the one live human-approval path, a different mechanism).

## If you change this
**Hits:** only its two importers: the example script and `tests/unit/test_d28_no_blocking_input_in_async.py`.
**Does not hit:** any tool, flow state or interface.

## Surfaces
None at runtime. The example script prints the prompts.

## See
`weebot/core/approval.py`
