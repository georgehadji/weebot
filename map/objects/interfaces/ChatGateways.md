---
type: object
name: Chat gateways
code: GatewayAdapter and six subclasses
cluster: interfaces
universe: live
status: verified
verified: 2026-10-31
commit: 7d205bb1
---

# Chat gateways

Adapters that take a message from Telegram, Slack, Discord, WhatsApp, Signal or email, run it through a `PlanActFlow`, and send the last assistant message back. Base class `GatewayAdapter` (`weebot/interfaces/gateways/base.py:97`).

## Why this shape
One base class holds what every platform needs: the allowlist check `is_authorized` (`base.py:105-137`, deny by default unless `gateway_auth_enabled` is off), `handle` (`:154-160`, returns the text unchanged; the inert safety gate is gone, so the tool guard chain is what judges actions), a `ponytail [mode]` parser and reply (`:162-207`; every adapter answers it after its sender check, without starting a run; `tests/unit/fixes/test_gateway_ponytail_command.py`) and media extraction from reply text (`:209-276`). Subclasses add only transport: polling or a webhook, signature check, send.

## Shape

| Adapter | File | Inbound | Started by | Session |
|---|---|---|---|---|
| `TelegramAdapter` | `gateways/telegram.py:52` | long-poll `getUpdates` (`:95-135`) | web lifespan when `telegram_bot_token` is set (`weebot/interfaces/web/main.py:280-306`) | `GatewayFlowResolver` keyed by chat (`:167-194, 239-244`); `/new`, `/reset` and "new session" stop the run and close the gateway session, `/stop` cancels the chat's run task (F1, `:201-254`, `:271-278`, `:297-314`) |
| `SignalAdapter` | `gateways/signal.py:31` | poll signal-cli REST (`:64-84`) | lifespan when `signal_account_number` is set (`main.py:309-325`) | new per message (`:105-109`) |
| `EmailAdapter` | `gateways/email.py:100` | IMAP poll (`:145-162, 240-295`) | lifespan when IMAP user and password are set (`main.py:327-352`) | new per message (`:196-197`) |
| `SlackAdapter` | `gateways/slack.py:29` | `POST /api/gateway/slack/events` (`weebot/interfaces/web/routers/slack_webhook.py:34-69`; acks, then spawns the event on the background-task owner, `:68`), HMAC plus a 5-minute timestamp window (`slack.py:53-71`) | lazily on first callback (`slack_webhook.py:90-121`) | new per message (`slack.py:129-132`) |
| `DiscordAdapter` | `gateways/discord.py:38` | `POST /api/gateway/discord/interactions` (`routers/discord_webhook.py:28-59`); answers deferred (type 5) at once, runs the flow in a background task and edits the original reply when it ends (`discord.py:196-203, 202-213, 233-252`, audit R09), Ed25519 plus a 5-minute timestamp window (`discord.py:35, 78-103`) | lazily (`discord_webhook.py:62-95`) | new per message (`discord.py:223-225`) |
| `WhatsAppAdapter` | `gateways/whatsapp.py:31` | `GET/POST /api/gateway/whatsapp/webhook` (`routers/whatsapp_webhook.py:36-80`; messages are spawned on the background-task owner, `:78`), `X-Hub-Signature-256`, fail closed without app secret unless `whatsapp_allow_unsigned_webhooks` (`whatsapp.py:65-92`) | lazily (`whatsapp_webhook.py:98-132`) | new per message (`whatsapp.py:116-120`) |

Every adapter runs a message the same way: `async with run_scope(session, llm, state_repo, profile_name) as flow` from `weebot/interfaces/factories.py:251-282`, which builds `build_tools(role="admin")` and a plan-act flow and tears the tools down when the run ends, however it ends (audit R05; `telegram.py:264`, `slack.py:135`, `discord.py:228`, `whatsapp.py:122`, `signal.py:114`, `email.py:203`; `tests/unit/fixes/test_r05_gateways_tear_down.py`). The `llm` each adapter gets is the container's bounded `LLMPort` (`infrastructure/LLMAdapters.md`). Email also drops its own address and automated senders (`email.py:173-179`). The allowlist is edited with `python -m cli.main gateway allowlist ...` (`cli/commands/gateway.py:107-172`).

Consequences (read from source, not run):
- No adapter passes a mediator or event bus to `create_flow`; `build_flow` resolves both from the shared container (`weebot/application/flows/flow_builder.py:114-125`), so a gateway flow can plan (`PlanningState` refuses to run without a mediator, `weebot/application/flows/states/planning.py:95-103`) and its events reach the bus the WebSocket broadcaster listens on (`main.py:216-219`).
- The flows resolve tools and collaborators through `shared_container()`, which is also the web lifespan's container (`main.py:186-190`; see `WebAPI.md`).
- Every allowlisted chat gets the `admin` tool role, which includes `bash`, `powershell` and `python_execute`; the web process approval channel is `FlowPauseApproval` (`main.py:203`), and no gateway has a way to answer a pause.
- `extract_media` turns an absolute path ending in a listed extension in the agent's reply into an attachment (`base.py:209-276`). Document types (`.pdf`, `.docx`, `.xlsx`, `.csv`, `.json`, `.yaml`, `.yml`, `.md`, `.txt`) only from inside the project root (F76, `:254-270`); images, audio and video from any path. Telegram then uploads the file (`telegram.py:331-337, 346-394`). The regex only matches paths starting with `/` (`base.py:92`), though the docstring names Windows paths (`:214`).
- Email authorizes on the allowlisted `From` address and also requires the mail server to have authenticated that domain (DMARC pass or aligned DKIM pass in the topmost `Authentication-Results` whose authserv-id is trusted: `EMAIL_TRUSTED_AUTHSERV_IDS`, else the IMAP host and, for Gmail, `mx.google.com`; `email.py:40-52, 74-97`; `tests/unit/fixes/test_email_sender_is_authenticated.py`, `test_s5_email_authserv_id.py`).
- Telegram loads the existing session inside `except Exception: pass` (`telegram.py:292-296`): a load error starts a fresh session with the same id. Each Telegram run is a task per chat (`_runs`, `telegram.py:260-282`), so the poll loop keeps reading; a second message during a run gets a hint to `/stop` instead of a second run (`tests/unit/fixes/test_f1_telegram_session_commands.py`).
- Slack, Discord, WhatsApp, Signal and email generate a new session id per message (`flow_session_id`, `base.py:56-64`), so no conversation carries over.
- `handle_ponytail_command` imports `cli.commands.ponytail` (`base.py:176`), an interfaces module depending on the CLI package, and sets a process-wide mode, so any allowlisted chat sender can change it for everyone.

## Connected to
- **Built by** the web lifespan (`WebAPI.md`) and the platform webhook routers. **Uses** `create_flow`/`build_tools` (`CLI.md`), `GatewayAuth` (`weebot/core/gateway_auth.py`), `GatewayFlowResolver` and `IGatewaySessionStorePort` (Telegram only, `main.py:283-293`).
- **Looks like but is not:** the generic `/api/webhook/run` (`routers/webhook.py`), which is not a `GatewayAdapter`; `atomic_mail` (agent-owned inbox tool), which is outbound/inbound mail as a tool, not a gateway.

## If you change this
**Hits:** every chat platform, the web lifespan startup, `gateway` CLI, tests `tests/unit/test_gateway_adapters.py`, `tests/unit/test_media_delivery.py`, `tests/unit/test_gateway_session.py`, `tests/unit/interfaces/test_discord_adapter.py`, `tests/unit/interfaces/gateways/test_discord_gateway_auth.py`, `tests/unit/interfaces/gateways/test_whatsapp_signature.py`, `tests/unit/fixes/test_w53_interface_roots.py`, `tests/unit/fixes/test_email_sender_is_authenticated.py`, `tests/unit/fixes/test_ssot_ponytail_modes.py`, `tests/unit/core/test_security_state_durability.py`, `tests/unit/test_latent_trap_fixes.py`, `tests/unit/test_rate_limit.py`.
**Does not hit:** the Web UI; the MCP server.

## Surfaces
Chat users on the six platforms; the admin who edits the allowlist.

## See
`weebot/interfaces/gateways/base.py`
