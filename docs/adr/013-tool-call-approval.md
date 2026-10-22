# ADR-013: How an "ask" verdict on a tool call is resolved

**Date:** 2026-10-22
**Status:** Approved 2026-10-22 (ICM fix plan W3.4; open questions resolved below). Implemented 2026-10-22; see `tasks/icm_fix_plan.md` W3.4/W3.5 result. Grant, deny and expiry are journaled since the same day (`tasks/remaining_fix_plan.md` B2a), and a browser round trip passed (B2c).
**Owner:** weebot maintainers
**Supersedes:** N/A
**Numbering note:** `ARCHITECTURE.md` also lists an unrelated "ADR-009"; this file series is `docs/adr/NNN-*.md`.

---

## Context

The guard chain (`weebot/application/services/tool_guards.py`, plan W3.1) gives every
`bash`, `powershell` and `python_execute` call one verdict: ALLOW, ASK or DENY. Today
**ASK has nowhere to go**: `bash`, `powershell` and `python_execute` refuse it
("requires user confirmation"), and once the chain enforces (W3.7, decision 1) so will
`GuardedTool`. Nothing in the code path asks a human.

What already exists, verified 2026-10-22:

- **Flow pause.** `pause_for_user()` (`application/flows/collaborators/user_pause.py:77`)
  sets WAITING and persists; `_mark_user_gate()` (`flows/states/executing.py:90`) records
  why, so `FlowRouter.resolve_initial_state` routes the reply. The inbound-mail gate and
  the constraint gate use it (`executing.py:286-338`).
- **`ToolApprovalEvent`** (`domain/models/event.py:111`, with `tool_name`, `arguments`,
  `risk_level`, `reason`, `prompt`) is handled: `executing.py:474` sets `hitl_paused`. It
  is **never emitted**.
- **`ApprovalManager`** (`core/approval.py:115`) has a console callback that reads stdin
  off the event loop and fails closed. It has no runtime caller (ghost). Its session cache
  approves by raw command string, and with `auto_deny_blocked=False` it can approve
  BLOCKED (F07).
- **`EgressGuard.approve_recipient()`** (`core/egress_guard.py:296`) persists a host to
  the allowlist. It has no caller, so a first-time host can only be allowed by editing the
  JSON file (F08).
- **Override token** (`tools/bash_tool.py:312-331`): `HMAC(secret, command)`, with no
  nonce, no expiry, and reusable forever (F11).
- **Decision 7:** the sandbox network is off by default, with egress approval for the
  first host. The per-host versus per-run mechanism is decided here.

Channels and whether a human can answer:

| Channel | Entry | Human present | Can block on input |
|---|---|---|---|
| CLI `flow run` | `cli/` | yes, if stdin is a TTY | yes |
| Web UI | `interfaces/web`, WebSocket events | yes | no, must pause and resume |
| Chat gateways (Telegram, Discord, Slack, WhatsApp) | `interfaces/gateways` | yes, the authorized sender | no, must pause and resume |
| MCP server | `weebot/mcp/server.py` | the MCP client decides | no |
| Cron, webhooks | `cron_agent_runner`, `routers/webhook.py` | no | no |

---

## Decision

### 1. One port, three strategies

`ApprovalPort` (`application/ports/approval_port.py`) answers one question: *is there a
grant for this exact call?* A channel is selected at the composition root:

- **Deny** (default; cron, webhooks, MCP, any non-TTY run). ASK is refused with the
  reason and the exact way to approve it from an interactive channel. This is today's
  behaviour, so it is the safe default.
- **Console** (CLI with a TTY). The call blocks on a prompt in a worker thread, reusing
  `console_approval_callback`. "y" issues a grant and the call proceeds at once.
- **Flow pause** (web UI, chat gateways). `GuardedTool` returns a result tagged
  `approval_required` and the executor emits `ToolApprovalEvent`. The flow pauses through
  `pause_for_user` with gate `"tool_approval"`. On resume, `FlowRouter` turns "yes" into
  a grant and re-runs the step; the call finds the grant and proceeds. "no" or anything
  else ends the step as refused.

### 2. A grant is single-use, exact, and short-lived

- **Fingerprint:** `sha256(tool_name + canonical JSON of the arguments)`, so changing a
  character, path or flag means a new approval. Approving by raw command string, as
  `ApprovalManager` does, is dropped.
- **Single use:** consumed by the first matching call.
- **Expiry:** 10 minutes, and scoped to the session.
- **DENY is never approvable.** BLOCKED, analyzer DANGEROUS and policy DENY have no
  approval route. `auto_deny_blocked` is removed.
- **`ApprovalManager` becomes the grant store** (decision 2): a session-scoped cache
  behind the port. Its "approve the whole session" switch is deleted.

### 3. Egress: "once" or "this host from now on"

For an egress ASK whose only reason is `FIRST_TIME_RECIPIENT`, the prompt offers *allow
once* or *always allow this host*. "Always" calls `EgressGuard.approve_recipient(host)`
(F08). ASKs that carry `SENSITIVE_PAYLOAD` or `UNTRUSTED_CONTEXT` offer *once* only.

**Sandbox network (decision 7): per call, not per host.**
- The sandbox runs with network off. A shell or Python call that the chain classifies as
  egress to host H, and that is approved, runs with `allow_network=True` for that call
  only.
- A per-host allowlist inside the sandbox needs an egress proxy or firewall rules that no
  backend has. Native and WSL2 cannot even enforce network-off (Sandbox card), so
  per-host would be a claim, not a control.
- W3.9 adds `SandboxCapability.NETWORK_ISOLATION`. When a backend cannot isolate, the
  approval prompt says the network was never off.

### 4. The override token is retired

`security_override` (F11) is removed. An administrator approves through the Console or
Flow-pause channel, which produces a single-use, fingerprinted, expiring grant: the
properties the token lacked.

### 5. Every request and answer is journaled

`approval_requested`, `approval_granted`, `approval_denied` and `approval_expired` go to
the event store with session, tool, fingerprint, guard and reason. The command text is
redacted through the existing secret redactor.

### 6. Rollout

Lands with the chain still in observe mode. Enforce (W3.7) is flipped only after:
- observe data has been reviewed, and
- the Flow-pause strategy works end to end in the web UI.

---

## Consequences

### Positive
- ASK means "a human decides" in every channel that has a human, and "no" everywhere else.
- `approve_recipient` and `ToolApprovalEvent` get their first callers.
- The ghost `ApprovalManager` is reused, not duplicated.
- Grants cannot be replayed, widened or kept.

### Negative
- Flow-pause re-runs the step, so a step that ran tools before the ASK runs them again.
  Steps are already re-runnable (UpdatingState retries), but non-idempotent tools earlier
  in the same step repeat.
- MCP clients get a refusal they cannot approve from inside the protocol.
- One more gate value (`"tool_approval"`) for `FlowRouter` to route.

### Alternatives rejected
- **Prompt inside the tool for every channel:** it blocks the web server and hangs headless
  runs.
- **Session-wide approval:** one "yes" would open every later call.
- **Approve by command text:** whitespace and quoting variants defeat it. A fingerprint over
  canonical arguments does not.
- **Per-host network allowlist inside the sandbox:** not enforceable on any current backend
  (section 3).

---

## Resolved questions (review 2026-10-22, draft answers accepted)

1. **MCP:** Deny. The MCP client's own tool-approval UI is not trusted, because clients differ and many auto-approve.
2. **Grant expiry:** 10 minutes.
3. **Chat gateways:** Flow pause, but only for the authorized sender (`gateway_auth_enabled`). Any other sender gets Deny.
4. **Fingerprint scope:** exact arguments. A changed `timeout` or `working_dir` needs a new approval.

## Related

- `tasks/icm_fix_plan.md` (W3.4, W3.5, W3.7, W3.9; decisions 1, 2, 7; F07, F08, F11)
- `weebot/application/services/tool_guards.py`, `weebot/core/approval.py`,
  `weebot/core/egress_guard.py`, `weebot/application/flows/collaborators/user_pause.py`
- ADR-006 (inbound mail gate: same pause pattern), ADR-007 (MCP inbound trust)
