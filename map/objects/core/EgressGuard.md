---
type: object
name: EgressGuard
code: EgressGuard, RecipientAllowlist, EgressDecision
cluster: core
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# EgressGuard

Looks at a pending tool call and decides whether it sends data out (curl POST, `git push`, browser form submit, Telegram message, JMAP email send) and, if so, whether it needs human approval. In enforcing mode a call that needs approval is replaced by an error result and does not run.

## Why this shape
Aimed at the "lethal trifecta": an agent that can read private data, ingest untrusted content and send data out can be talked into leaking (`weebot/core/egress_guard.py:1-11`). So the check is on the outbound action, keyed on stable identifiers (host, email address, chat id), never display names (`:13-15, 189-195`). Like the other guards it fails closed: if the guard cannot be built, outbound-capable tools are refused (`application/agents/executor/_tool_executor.py:232-246`).

## Shape
- `classify(tool_name, args, untrusted_context_active)` (`egress_guard.py:249`):
  1. `_detect_egress` returns `(recipient, is_egress)`; not egress → no decision needed (`:263-265, 304-353`).
  2. Payload = all string args plus JSON of list/dict args (`:355-363`); scanned against 11 sensitive patterns (API keys, secrets, passwords, tokens, `Bearer`, `ghp_`, `sk-`, AWS `AKIA`, private keys, DB URLs, bulk email-plus-data rows) → reason `SENSITIVE_PAYLOAD` (`:63-78, 365-373`).
  3. Unknown recipient (none extractable, or not in the allowlist) → `FIRST_TIME_RECIPIENT` (`:282-284`).
  4. `untrusted_context_active` → `UNTRUSTED_CONTEXT`, which always requires approval even for a known recipient (`:286-291`).
  5. `requires_approval` is true if any reason was added (`:293`). Every egress to a recipient not on the allowlist therefore needs approval, whether or not the payload looks sensitive.
- What counts as egress: `bash`/`bash_execute`/`powershell`/`shell`/`cmd`/`terminal` commands matching curl/wget with data, `Invoke-WebRequest`/`irm` with a body or POST, `nc`, `scp`, `sftp`, `Send-MailMessage`, `git push` (`:85-112, 309-314`); browser tools `advanced_browser`, `browser_navigator`, `browser_tool`, `computer_use` on submit-style actions or with POST data (`:119-132, 317-326`); `atomic_mail` `jmap_request` that submits (reads like `list_inbox` and dry runs excluded, `:332-345`); `telegram_send`, `windows_toast`, `notification`, `schedule_tool` (`:135-142, 348-351`).
- `RecipientAllowlist`: JSON file, default `weebot_egress_allowlist.json` at the repo root or `WEEBOT_EGRESS_ALLOWLIST`; atomic writes; an unreadable file is preserved and the list starts empty (`:51-57, 189-229`). The file is in `.gitignore:179`.
- Enforcement switch: `WEEBOT_EGRESS_ENFORCE`, default true; false = detect-only (log, allow) (`:41-47`).

Where it runs: `ToolExecutor.execute_tool` calls `guard.classify` before every tool call; a blocked call returns "Outbound action blocked — requires human approval" and is not executed (`_tool_executor.py:229-257`, message `:29-39`). `_untrusted_context_active` is set after any successful tool result that `taints_egress_context(name)` says carries external content, and stays set for that `ToolExecutor` instance (`:290-299`). A `ToolExecutor` belongs to an `ExecutorAgent`, and the Mediator path builds one executor per step, so the flag likely resets each step (inference, not tested).

Consequences (read from source, not run):
- Since 2026-10-22 (plan W3.8, W3.9): `python_execute` code that imports a network library is egress (F09). `network_use()` names the host a shell download or install reaches, which `ToolExecutor` uses to clear per-call sandbox network.
- Fixed 2026-10-22 (plan W3.5, ADR-013): `approve_recipient` is called by `tool_approval.allow_host` when a human answers "always" to a first-time-host egress approval (Console or Flow pause). `ToolExecutor`'s egress ASK now goes to the approval channel; the default Deny channel keeps the old blocked result. At `f00ea38`: **nothing in the repo called `approve_recipient`** (grep, 2026-10-21). The block message says a human must approve, but there is no in-flow way to do so; the allowlist can only grow by someone editing `weebot_egress_allowlist.json`. Until then every first egress to a new host is blocked.
- `python_execute` is not in the egress list, so Python code that posts data (for example with `requests`) is not classified as egress. Only the shell, browser, mail, notification and scheduling tools are.
- The host is extracted from the first `http(s)://` URL in the command; a command with no URL is a "first-time recipient" (`:375-378`).

## Connected to
- **Built by** `FactoriesMixin._create_egress_guard` and registered in `configure_defaults` (`application/di/_factories.py:303-307`, `di/__init__.py:301-303`); resolved lazily by `ToolExecutor` with a direct-construction fallback (`_tool_executor.py:86-125`).
- **Related:** `core/trust_boundary.py` (`is_untrusted_tool`, `taints_egress_context`, fencing of untrusted output), the inbound-mail gate in `ExecutingState` (uses `ExecApprovalPolicy`, not this guard), `services/constraint_compilers.py` (mentions the outbound-mail branch).
- **Looks like but is not:** `BashGuard` (rates what a command *does locally*); `ExecApprovalPolicy` (asks before destructive commands); this guard concerns data leaving the machine.

## If you change this
**Hits:** every tool call (the check runs before execution); the tools named in the lists above; `.env` setting `WEEBOT_EGRESS_ENFORCE`; the allowlist file; tests `tests/unit/test_egress_guard.py`, `tests/unit/test_tool_executor_egress.py`.
**Does not hit:** BashGuard; ExecApprovalPolicy; the state repository.

## Surfaces
The agent sees the "Outbound action blocked" error text; operators control it with `WEEBOT_EGRESS_ENFORCE` and the allowlist file.

## See
`weebot/core/egress_guard.py`
