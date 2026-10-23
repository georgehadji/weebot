---
type: object
name: EgressGuard
code: EgressGuard, RecipientAllowlist, EgressDecision
cluster: core
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# EgressGuard

Looks at a pending tool call and decides whether it sends data out (curl POST, `git push`, network-importing Python, browser form submit, Telegram message, JMAP email send) and, if so, whether it needs human approval. In enforcing mode a call that needs approval goes to the approval channel; when that channel denies, the call is replaced by an error result and does not run.

## Why this shape
Aimed at the "lethal trifecta": an agent that can read private data, ingest untrusted content and send data out can be talked into leaking (`weebot/core/egress_guard.py:1-11`). So the check is on the outbound action, keyed on stable identifiers (host, email address, chat id), never display names (`:13-15, 239-245`). Like the other guards it fails closed: if the guard cannot be built, outbound-capable tools are refused (`weebot/application/agents/executor/_tool_executor.py:227-246, 332-346`).

## Shape
- `EgressGuard` (`egress_guard.py:287`); `classify(tool_name, args, untrusted_context_active)` (`:299-346`):
  1. `_detect_egress`, then `_browser_egress`, return `(recipient, is_egress)`; not egress means no decision is needed (`:312-317`).
  2. Payload = all string args plus JSON of list/dict args (`:323, 459-467`); scanned against 11 sensitive patterns (API keys, secrets, passwords, tokens, `Bearer`, `ghp_`, `sk-`, AWS `AKIA`, private keys, DB URLs, bulk email-plus-data rows) giving reason `SENSITIVE_PAYLOAD` (`:63-78, 325-329, 469-477`).
  3. Unknown recipient (none extractable, or not in the allowlist) gives `FIRST_TIME_RECIPIENT` (`:331-336`).
  4. `untrusted_context_active` gives `UNTRUSTED_CONTEXT`, which requires approval even for a known recipient (`:338-343`).
  5. `requires_approval` is true if any reason was added (`:345`). Every egress to a recipient not on the allowlist therefore needs approval, whether or not the payload looks sensitive.
- What counts as egress:
  - `bash`/`bash_execute`/`powershell`/`shell`/`cmd`/`terminal` commands matching curl/wget with data, `Invoke-WebRequest`/`irm` with a body or POST, `nc`, `scp`, `sftp`, `Send-MailMessage`, `git push`, or `python -c` that imports a network library (`:85-112, 130-138, 398-405`).
  - `python_execute`/`python` code that imports a network library such as `requests`, `httpx`, `urllib`, `socket` (plan W3.8, F09) (`:114-125, 443-449`).
  - Browser tools `advanced_browser`, `browser_navigator`, `browser_tool`, `computer_use` on submit-style actions or with POST data (`:161-174, 412-422`); `camofox_browser` `type` (`:407-410`); a browser/scraper URL that holds a secret, and `advanced_browser` page writes (`fill`, `type`, `select`, `evaluate`) once the context is tainted (F41) (`:176-182, 348-360`).
  - `atomic_mail` `jmap_request` that submits (`EmailSubmission`); read presets like `list_inbox` and dry runs are excluded (`:194-199, 424-441`).
  - `telegram_send`, `windows_toast`, `notification`, `schedule_tool` always (`:184-192, 451-455`).
- Recipient: the host of the first `http(s)://` URL in the command or code; no URL means no recipient, which counts as first-time (`:479-482, 331-336`).
- `network_use(tool_name, args)` (plan W3.9): says whether a shell call reaches the network without being egress (downloads, package installs, git remotes, `docker pull`) and which host: the URL host, a `git@host:` remote, or the implied registry (`:140-154, 362-382`).
- `RecipientAllowlist`: JSON file, default `weebot_egress_allowlist.json` at the repo root or `WEEBOT_EGRESS_ALLOWLIST` (`:50-57`); atomic writes; an unreadable file is preserved and the list starts empty (`:239-279`). `approve_recipient` persists a host (`:387-389`). The file is in `.gitignore:179`.
- Enforcement switch: `WEEBOT_EGRESS_ENFORCE`, default true; false means detect-only (log, allow) (`:41-47`).

Where it runs: `ToolExecutor._get_egress_guard` constructs `EgressGuard()` lazily and latches only a successful build (`_tool_executor.py:193-225`). `execute_tool` calls `guard.classify` before every tool call (`:349-352`). When approval is required and enforcement is on, `_ask_about_egress` sends a `ToolCallApproval` to the current approval channel: approved runs the call, pending pauses the flow, denied returns "Outbound action blocked — requires human approval" (`:42-72, 353-362`, message `:29-39`). Detect-only logs and allows (`:363-366`). A non-egress call that reaches the network while the sandbox network is off asks through the same channel (`:75-119, 367-375`).

Taint: after a successful result from a tool that `taints_egress_context(name)` flags, the session is marked untrusted (`_tool_executor.py:419-445`). The mark is kept per session id in a process-wide set, so it survives the per-step executor rebuild but not a new process (`:129-132, 170-179`). A local (`file://`, loopback) browser tab and a file the session wrote itself do not taint (`:428-443`).

Consequences (read from source, not run):
- "Always" on an approval for a first-time host (offered only when `FIRST_TIME_RECIPIENT` is the sole reason, `_tool_executor.py:55, 63`) calls `tool_approval.allow_host`, which calls `approve_recipient` (`weebot/application/services/tool_approval.py:154-155, 162-167, 323-324`).
- The default approval channel is `DenyApproval` (`tool_approval.py:172`), so with no Console or Flow channel set, every first egress to a new host is still blocked.

## Connected to
- **Built by** `ToolExecutor._get_egress_guard`, one per executor (`_tool_executor.py:193-225`); there is no DI binding (`egress_guard.py:489-492`). `tool_approval.allow_host` builds a throwaway instance only to write the allowlist (`tool_approval.py:162-167`).
- **Related:** `weebot/core/trust_boundary.py` (`is_untrusted_tool` `:141`, `taints_egress_context` `:160`), `application/services/tool_approval.py` (the approval channel), the inbound-mail gate in `ExecutingState`.
- **Looks like but is not:** `BashGuard` (rates what a command *does locally*); `ExecApprovalPolicy` (asks before destructive commands); this guard concerns data leaving the machine.

## If you change this
**Hits:** every tool call (the check runs before execution); the tools named in the lists above; the sandbox-network clearance (`network_use`); `.env` setting `WEEBOT_EGRESS_ENFORCE`; the allowlist file; tests `tests/unit/test_egress_guard.py`, `tests/unit/test_tool_executor_egress.py`.
**Does not hit:** BashGuard; ExecApprovalPolicy; the state repository.

## Surfaces
The agent sees the "Outbound action blocked" error text; humans answer the approval prompt (Console or Flow pause); operators control it with `WEEBOT_EGRESS_ENFORCE` and the allowlist file.

## See
`weebot/core/egress_guard.py`
