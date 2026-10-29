---
type: object
name: Chat gateways
code: GatewayAdapter and six subclasses
cluster: interfaces
universe: live
status: stale
verified: 2026-10-25
commit: 7effa9ba
---

# Chat gateways

Adapters that take a message from Telegram, Slack, Discord, WhatsApp, Signal or email, run it through a `PlanActFlow`, and send the last assistant message back. Base class `GatewayAdapter` (`weebot/interfaces/gateways/base.py:58`).

## Why this shape
One base class holds what every platform needs: a `SafetyChecker` over the inbound text (`base.py:64, 116-123`), the allowlist check `is_authorized` (`:67-99`, deny by default unless `gateway_auth_enabled` is off), the `ponytail [mode]` command (`:125-170`) and media extraction from reply text (`:172-239`). Subclasses add only transport: polling or a webhook, signature check, send.

## Shape

| Adapter | File | Inbound | Started by | Session |
|---|---|---|---|---|
| `TelegramAdapter` | `gateways/telegram.py:38` | long-poll `getUpdates` (`:77-107`) | web lifespan when `telegram_bot_token` is set (`weebot/interfaces/web/main.py:271-301`) | `GatewayFlowResolver` keyed by chat (`:197-208`); `/new`, `/reset` via `GatewayCommandDispatcher` (`:191-195`) |
| `SignalAdapter` | `gateways/signal.py:25` | poll signal-cli REST (`:58-75`) | lifespan when `signal_account_number` is set (`main.py:303-320`) | new per message (`:98-101`) |
| `EmailAdapter` | `gateways/email.py:53` | IMAP poll (`:96-113, 200-258`) | lifespan when IMAP user and password are set (`main.py:322-346`) | new per message (`:149-150`) |
| `SlackAdapter` | `gateways/slack.py:24` | `POST /api/gateway/slack/events` (`weebot/interfaces/web/routers/slack_webhook.py:34-69`; acks, then runs the event on `BackgroundTasks`, `:68`), HMAC (`slack.py:48`) | lazily on first callback (`slack_webhook.py:90-121`) | new per message (`slack.py:121-126`) |
| `DiscordAdapter` | `gateways/discord.py:33` | `POST /api/gateway/discord/interactions` (`routers/discord_webhook.py:28-60`); answers deferred (type 5) at once, runs the flow in a background task and edits the original reply when it ends (`discord.py:191-195, 197-207, 229`, audit R09), Ed25519 plus a 5-minute timestamp window (`discord.py:73-98`) | lazily (`discord_webhook.py:63-96`) | new per message (`discord.py:215-218`) |
| `WhatsAppAdapter` | `gateways/whatsapp.py:26` | `GET/POST /api/gateway/whatsapp/webhook` (`routers/whatsapp_webhook.py:36-80`; messages run on `BackgroundTasks`, `:78`), `X-Hub-Signature-256`, fail closed without app secret unless `whatsapp_allow_unsigned_webhooks` (`whatsapp.py:60-87`) | lazily (`whatsapp_webhook.py:98-132`) | new per message (`whatsapp.py:110-113`) |

Every adapter runs a message the same way: `async with run_scope(session, llm, state_repo, profile_name) as flow` from `weebot/interfaces/factories.py:252`, which builds `build_tools(role="admin")` and a plan-act flow and tears the tools down when the run ends, however it ends (audit R05; `telegram.py:223`, `slack.py:129`, `discord.py:198`, `whatsapp.py:116`, `signal.py:104`, `email.py:166`; `tests/unit/fixes/test_r05_gateways_tear_down.py`). The `llm` each adapter gets is the container's bounded `LLMPort` (`infrastructure/LLMAdapters.md`). Email also drops its own address and automated senders (`email.py:122-130`). The allowlist is edited with `python -m cli.main gateway allowlist ...` (`cli/commands/gateway.py:107-172`).

Consequences (read from source, not run):
- No adapter passes a mediator or event bus to `create_flow`; `build_flow` resolves both from the shared container (`weebot/application/flows/flow_builder.py:80-93`), so a gateway flow can plan (`PlanningState` refuses to run without a mediator, `weebot/application/flows/states/planning.py:95-103`) and its events reach the bus the WebSocket broadcaster listens on (`main.py:215-218`).
- The flows resolve tools and collaborators through `shared_container()`, which is also the web lifespan's container (`main.py:184-190`; see `WebAPI.md`).
- Every allowlisted chat gets the `admin` tool role, which includes `bash`, `powershell` and `python_execute`; the web process approval channel is `FlowPauseApproval` (`main.py:202`), and no gateway has a way to answer a pause.
- `extract_media` turns an absolute path ending in a listed extension in the agent's reply into an attachment (`base.py:195-234`). Document types (`.pdf`, `.docx`, `.xlsx`, `.csv`, `.json`, `.yaml`, `.yml`, `.md`, `.txt`) only from inside the project root (F76, `:219-231`); images, audio and video from any path. Telegram then uploads the file (`telegram.py:282-288, 301-349`). The regex only matches paths starting with `/` (`base.py:53`), though the docstring names Windows paths (`:177`).
- Email authorizes on the allowlisted `From` address and also requires the mail server to have authenticated that domain (DMARC pass or aligned DKIM pass in the topmost `Authentication-Results` whose authserv-id is trusted: `EMAIL_TRUSTED_AUTHSERV_IDS`, else the IMAP host and, for Gmail, `mx.google.com`; `email.py:74`; `tests/unit/fixes/test_email_sender_is_authenticated.py`, `test_s5_email_authserv_id.py`).
- Telegram loads the existing session inside `except Exception: pass` (`telegram.py:246-251`): a load error starts a fresh session with the same id. `/new` handled by the dispatcher only replies "will be reset" (`:262-263`); the reset itself happens only for the plain-text forms (`:210-220`).
- Slack, Discord, WhatsApp, Signal and email generate a new session id per message, so no conversation carries over.
- `handle_ponytail_command` imports `cli.commands.ponytail` (`base.py:139`), an interfaces module depending on the CLI package.

## Connected to
- **Built by** the web lifespan (`WebAPI.md`) and the platform webhook routers. **Uses** `create_flow`/`build_tools` (`CLI.md`), `GatewayAuth` (`weebot/core/gateway_auth.py`), `SafetyChecker` (`weebot/core/safety.py`), `GatewayFlowResolver` and `IGatewaySessionStorePort` (Telegram only, `main.py:278-289`).
- **Looks like but is not:** the generic `/api/webhook/run` (`routers/webhook.py`), which is not a `GatewayAdapter`; `atomic_mail` (agent-owned inbox tool), which is outbound/inbound mail as a tool, not a gateway.

## If you change this
**Hits:** every chat platform, the web lifespan startup, `gateway` CLI, tests `tests/unit/test_gateway_adapters.py`, `tests/unit/test_media_delivery.py`, `tests/unit/test_gateway_session.py`, `tests/unit/interfaces/test_discord_adapter.py`, `tests/unit/interfaces/gateways/test_discord_gateway_auth.py`, `tests/unit/interfaces/gateways/test_whatsapp_signature.py`, `tests/unit/fixes/test_w53_interface_roots.py`, `tests/unit/fixes/test_email_sender_is_authenticated.py`, `tests/unit/fixes/test_ssot_ponytail_modes.py`, `tests/unit/core/test_security_state_durability.py`, `tests/unit/test_latent_trap_fixes.py`, `tests/unit/test_rate_limit.py`.
**Does not hit:** the Web UI; the MCP server.

## Surfaces
Chat users on the six platforms; the admin who edits the allowlist.

## See
`weebot/interfaces/gateways/base.py`
