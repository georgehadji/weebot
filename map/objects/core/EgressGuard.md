---
type: object
name: EgressGuard
code: EgressGuard, RecipientAllowlist, EgressDecision
cluster: core
universe: live
status: verified
verified: 2026-10-30
commit: 8e6d1cca
---

# EgressGuard

Looks at a pending tool call and decides whether it sends data out (curl POST, `git push`, network-importing Python, browser form submit, Telegram message, JMAP email send) and, if so, whether it needs human approval. In enforcing mode a call that needs approval goes to the approval channel; when that channel denies, the call is replaced by an error result and does not run.

## Why this shape
Aimed at the "lethal trifecta": an agent that can read private data, ingest untrusted content and send data out can be talked into leaking (`weebot/core/egress_guard.py:1-11`). So the check is on the outbound action, keyed on stable identifiers (host, email address, chat id), never display names (`:13-15, 328-334`). Like the other guards it fails closed: if the guard cannot be built, outbound-capable tools are refused (`weebot/application/agents/executor/_tool_executor.py:298-351, 445-459`).

## Shape
- `EgressGuard` (`egress_guard.py:376`); `classify(tool_name, args, untrusted_context_active)` (`:388-438`):
  1. `_detect_egress`, then `_browser_egress`, then (tainted session only) `_network_capable` return `(recipient, is_egress)`; not egress means no decision is needed (`:402-409`).
  2. Payload = all string args plus JSON of list/dict args (`:415, 578-586`); scanned against 11 sensitive patterns (API keys, secrets, passwords, tokens, `Bearer`, `ghp_`, `sk-`, AWS `AKIA`, private keys, DB URLs, bulk email-plus-data rows) giving reason `SENSITIVE_PAYLOAD` (`:66-81, 417-421, 588-596`).
  3. Unknown recipient (none extractable, or not in the allowlist) gives `FIRST_TIME_RECIPIENT` (`:423-428`).
  4. `untrusted_context_active` gives `UNTRUSTED_CONTEXT`, which requires approval even for a known recipient (`:430-435`).
  5. `requires_approval` is true if any reason was added (`:437`). Every egress to a recipient not on the allowlist therefore needs approval, whether or not the payload looks sensitive.
- What counts as egress:
  - `bash`/`bash_execute`/`powershell`/`shell`/`cmd`/`terminal` commands matching curl/wget with data, `Invoke-WebRequest`/`irm` with a body or POST, `nc`, `scp`, `sftp`, `Send-MailMessage`, `git push`, or `python -c` that imports a network library (`:88-115, 133-141, 519-524`).
  - `python_execute`/`python` code that imports a network library such as `requests`, `httpx`, `urllib`, `socket` (plan W3.8, F09) (`:119-128, 562-568`).
  - Browser tools `advanced_browser`, `browser_navigator`, `browser_tool`, `computer_use` on submit-style actions or with POST data (`:175-188, 531-541`); `camofox_browser` `type` (`:526-529`); a browser/scraper URL that holds a secret, and `advanced_browser` page writes (`fill`, `type`, `select`, `evaluate`) once the context is tainted (F41) (`:193-196, 440-452`).
  - `atomic_mail` `jmap_request` that submits: inline `ops` are judged after `$VAR` substitution by exact method name (`EmailSubmission/set`), and unreadable ops count as a send (`sends_mail`, `weebot/core/jmap_ops.py`; audit R02); read presets like `list_inbox` and dry runs are excluded (`egress_guard.py:213, 547-560`).
  - In a tainted session only (A21, `_network_capable`, `:454-468`; patterns `:147-168`): any shell call that can reach the network (downloads, DNS lookups, .NET web clients, sockets) and all non-blank `python_execute` code. The decision is `network_only` (`:237`), so the effect ledger does not skip a repeat.
  - `telegram_send`, `windows_toast`, `notification`, `schedule_tool` always (`:198-206, 570-574`).
- Recipient: the host of the first `http(s)://` URL in the command or code; no URL means no recipient, which counts as first-time (`:598-601, 426-428`).
- `network_use(tool_name, args)` (plan W3.9): says whether a shell call reaches the network without being egress (downloads, package installs, git remotes, `docker pull`) and which host: the URL host, a `git@host:` remote, or the implied registry (`:143-157, 470-490`).
- `RecipientAllowlist`: JSON file, default `weebot_egress_allowlist.json` at the repo root or `WEEBOT_EGRESS_ALLOWLIST` (`:53-60`); atomic writes; an unreadable file is preserved and the list starts empty (`:328-368`). `approve_recipient` persists a host (`:503-508`). The file is in `.gitignore:180`.
- Internal targets (loopback, link-local, private addresses, `localhost`; `classify_host`, `:256-320`) are never known and never stored as "always" (`is_known_recipient`, `approve_recipient`, `:497-508`).
- Enforcement switch: `WEEBOT_EGRESS_ENFORCE`, default true; false means detect-only (log, allow) (`:44-50`).

Where it runs: `ToolExecutor._get_egress_guard` constructs `EgressGuard()` lazily and latches only a successful build (`_tool_executor.py:298-330`). `execute_tool` calls `guard.classify` before every tool call (`:463-466`). When approval is required and enforcement is on, `_ask_about_egress` sends a `ToolCallApproval` to the current approval channel: approved runs the call, pending pauses the flow, denied returns "Outbound action blocked — requires human approval" (`:48-78, 489-498`, message `:35-45`). Detect-only logs and allows (`:499-502`). A non-egress call that reaches the network while the sandbox network is off asks through the same channel (`_clear_network_use`, `:105-154, 503-511`). `GuardedTool` also runs this guard for the MCP server's shell tools (`EgressAdapter`, `application/services/tool_guards.py:210-238`).

After untrusted content (decision D5): in a tainted session, a call that does more than read asks through the same channel even when it is not egress (`reads_only`, `application/services/tool_guards.py:375-397`; `_ask_after_untrusted_content`, `_tool_executor.py:81-102`, called `:513-529`). An egress approval already covers the call, and outside `enforce` mode the gate only logs (`:519-520`).

Effect ledger (ORCH-2): an egress call this session already completed is not run again, and a completed one is recorded (`_tool_executor.py:467-488, 558-568`; `application/services/effect_ledger.py`, key from `core/effect_key.py`).

Taint: after a non-error result from a tool whose declared `OutputTrust` is EXTERNAL, the session is marked untrusted (`must_taint(trust_of(tool_obj), is_error)`, `_tool_executor.py:614-617`; `weebot/core/trust_boundary.py:58-90`); an injection-scan hit can escalate a fixed-schema tool (`taint_session`, `:621-629`). The mark is kept per session id in a `SessionScope` (`_session_scope.py:33-65`, `_tool_executor.py:209-218`) and appended to the event store as `session_flag` rows, replayed once per session, so a resume in a new process keeps it (`_persist_flag`, `_hydrate_session_state`, `:230-278`); an unreadable store is assumed tainted (`:259-262`). A local (`file://`, loopback) browser tab and a file the session wrote itself do not taint (`:595-616`).

Consequences (read from source, not run):
- "Always" on an approval for a first-time host (offered only when `FIRST_TIME_RECIPIENT` is the sole reason, `_tool_executor.py:61, 69`) calls `tool_approval.allow_host`, which calls `approve_recipient` (`weebot/application/services/tool_approval.py:155-156, 163-168, 358`).
- The default approval channel is `DenyApproval` (`tool_approval.py:104, 173`), so with no Console or Flow channel set, every first egress to a new host is still blocked.

## Connected to
- **Built by** `ToolExecutor._get_egress_guard`, one per executor (`_tool_executor.py:298-330`); there is no DI binding (`egress_guard.py:608-610`, `application/di/__init__.py:331-333`). `tool_approval.allow_host` builds a throwaway instance only to write the allowlist (`tool_approval.py:163-168`).
- **Related:** `weebot/core/trust_boundary.py` (`trust_of` `:58`, `must_fence` `:74`, `must_taint` `:79`, `escalate` `:93`; the verdict comes from each tool's `OutputTrust`), `application/services/tool_approval.py` (the approval channel), the inbound-mail gate in `ExecutingState`.
- **Looks like but is not:** `BashGuard` (rates what a command *does locally*); `ExecApprovalPolicy` (asks before destructive commands); this guard concerns data leaving the machine.

## If you change this
**Hits:** every tool call (the check runs before execution); the tools named in the lists above; the sandbox-network clearance (`network_use`); `.env` setting `WEEBOT_EGRESS_ENFORCE`; the allowlist file; tests `tests/unit/test_egress_guard.py`, `tests/unit/test_tool_executor_egress.py`, `tests/unit/test_effect_ledger.py`, `tests/unit/test_session_security_state_durable.py`.
**Does not hit:** BashGuard; ExecApprovalPolicy; the state repository.

## Surfaces
The agent sees the "Outbound action blocked" error text; humans answer the approval prompt (Console or Flow pause); operators control it with `WEEBOT_EGRESS_ENFORCE` and the allowlist file.

## See
`weebot/core/egress_guard.py`
