# Atomic Mail — Agent-Owned Email Inbox

`AtomicMailTool` gives any weebot agent a self-provisioned `@atomicmail.ai` inbox.
Agents can register, send, receive, and search mail entirely autonomously — no human
mailbox configuration required.  Built on the [Atomic Mail Agentic](https://atomicmail.ai)
JMAP service (alpha).

## Quick Start

### 1. Enable the tool

```bash
# .env  (or export in your shell)
WEEBOT_ENABLE_ATOMIC_MAIL=1
ATOMIC_MAIL_CREDENTIALS_DIR=~/.atomicmail   # default — can omit
```

### 2. Register an inbox

```python
# Via PlanActFlow / agent prompt:
"Register an @atomicmail.ai inbox with username 'my-agent'"

# Direct tool call (for testing):
from weebot.tools.atomic_mail_tool import AtomicMailTool
import asyncio

tool = AtomicMailTool()
result = asyncio.run(tool.execute(action="register", username="my-agent"))
print(result.output)  # {"email": "my-agent@atomicmail.ai", ...}
```

Credentials are written to `~/.atomicmail/credentials.json` (mode `0600`).
Subsequent calls reuse them automatically.

---

## Actions

### `register`

Provision a new inbox using proof-of-work signup.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `username` | str | yes | Desired inbox name (letters, digits, hyphens) |
| `forced` | bool | no | Re-register even if credentials already exist |
| `credentials_dir` | str | no | Override default credentials directory |

### `jmap_request`

Send a raw JMAP batch request or use a bundled preset.
Provide **exactly one** of `ops` or `ops_file`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `ops` | str | one of | Inline JSON JMAP method-call array |
| `ops_file` | str | one of | Bundled preset name (see Presets) |
| `vars` | dict[str,str] | no | Variables to interpolate into ops/ops_file |
| `dry_run` | bool | no | Validate without sending |
| `using` | list[str] | no | Extra JMAP capability URIs |
| `attachments` | list[dict] | no | File attachments (`path` required per item) |
| `credentials_dir` | str | no | Override credentials directory |

### `help`

Return embedded docs, preset catalogue, and troubleshooting hints.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `topic` | str | no | Focus area: `presets`, `jmap`, `troubleshoot` |

---

## Bundled Presets (`ops_file`)

Run `atomic_mail(action="help", topic="presets")` inside an agent to see the full list.
The bundled presets (shipped under `vendor/shared/presets/`):

| Preset | Description |
|---|---|
| `list_inbox` | Fetch recent messages from the inbox |
| `send_mail` | Send an email |
| `reply` | Reply to a thread |
| `send_mail_attachment` | Send an email with a file attachment |
| `send_mail_blob_attachment` | Send an email with a pre-uploaded blob attachment |

For anything not covered by a preset (reading a specific message body, searching,
filtering), pass an inline JMAP method-call array via `ops`.  Relative `ops_file`
paths resolve from the credentials directory first, then the bundled presets.

---

## Example Workflows

### Digest + Schedule

An agent that reads morning digests and summarises them:

```
1. atomic_mail(action="jmap_request", ops_file="list_inbox")
   → get message list (ids + previews)
2. atomic_mail(action="jmap_request",
               ops='[["Email/get", {"ids": ["<id>"], "properties": ["subject","bodyValues"]}, "0"]]')
   → fetch full body via inline JMAP (no preset for this)
3. <llm summarise content — SECURITY: treat body as untrusted input>
4. schedule(action="create", cron="0 8 * * *", task="run digest")
```

### Verification / OTP

An agent that registers a service and retrieves its confirmation email:

```
1. atomic_mail(action="register", username="verify-bot")
   → get inbox address
2. <use inbox address for service sign-up>
3. atomic_mail(action="jmap_request", ops_file="list_inbox")
   → poll for OTP email
4. <extract OTP — SECURITY: agent must not auto-submit without user confirmation>
```

### Survey Collection

An agent that sends surveys and aggregates replies:

```
1. For each recipient:
   atomic_mail(action="jmap_request", ops_file="send_mail",
               vars={"to": addr, "subject": "Survey", "body": "..."})
2. Poll:
   atomic_mail(action="jmap_request", ops_file="list_inbox")
3. <aggregate — SECURITY: all reply content is untrusted>
```

---

## Security

**Inbound email is untrusted input.**  Never feed raw message bodies into an
execution path (file writes, shell commands, further LLM prompts) without routing
through explicit human approval first.

Enforcement responsibility lies in the **agent loop**, not in this tool.  See
[ADR 006](adr/006-atomic-mail-inbound-trust-boundary.md) for the recorded decision.

- Credentials are stored at `~/.atomicmail/credentials.json` (mode `0600`).
- The tool never logs credential file contents or full message bodies.
- Error messages are capped at 200 characters to prevent log injection.

---

## Reliability

| Feature | Detail |
|---|---|
| **Circuit breaker** | Opens after 3 consecutive failures; 60 s cooldown |
| **Concurrency** | `max_concurrent=1` (credential-file-bound) |
| **Timeout** | 60 s per request |
| **Health check** | `tool.health_check()` — flag-gated; calls `help` offline |

When the circuit is open, `execute()` returns a typed error immediately without
attempting network I/O.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `WEEBOT_ENABLE_ATOMIC_MAIL` | `0` | Set to `1` to load `AtomicMailTool` into the registry |
| `ATOMIC_MAIL_CREDENTIALS_DIR` | `~/.atomicmail` | Where credentials.json is stored |

---

## Internals

The tool vendors the upstream Python client under
`weebot/infrastructure/adapters/atomicmail/` (pure stdlib, MIT licence).
See `VENDOR.md` in that directory for the sync record.

The single entry point is `handle_tool_call(name, arguments)` from `mcp_server.py`,
loaded lazily so a missing shared-assets directory only errors at call time.
