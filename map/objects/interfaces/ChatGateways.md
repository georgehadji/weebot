---
type: object
name: Chat gateways
code: GatewayAdapter and six subclasses
cluster: interfaces
universe: live
status: verified
verified: 2026-10-23
commit: c2f39937
---

# Chat gateways

Adapters that take a message from Telegram, Slack, Discord, WhatsApp, Signal or email, run it through a `PlanActFlow`, and send the last assistant message back. Base class `GatewayAdapter` (`weebot/interfaces/gateways/base.py:77`).

## Why this shape
One base class holds what every platform needs: a `SafetyChecker` over the inbound text (`base.py:83, 135-142`), the allowlist check `is_authorized` (`:86-118`, deny by default unless `gateway_auth_enabled` is off), the `ponytail [mode]` command (`:144-189`) and media extraction from reply text (`:191-248`). Subclasses add only transport: polling or a webhook, signature check, send.

## Shape

| Adapter | File | Inbound | Started by | Session |
|---|---|---|---|---|
| `TelegramAdapter` | `gateways/telegram.py:38` | long-poll `getUpdates` (`:77-107`) | web lifespan when `telegram_bot_token` is set (`weebot/interfaces/web/main.py:266-291`) | `GatewayFlowResolver` keyed by chat (`:200-208`); `/new`, `/reset` via `GatewayCommandDispatcher` (`:192-195`) |
| `SignalAdapter` | `gateways/signal.py:25` | poll signal-cli REST (`:58-75`) | lifespan when `signal_account_number` is set (`main.py:295-310`) | new per message |
| `EmailAdapter` | `gateways/email.py:35` | IMAP poll (`:78-95`) | lifespan when IMAP user and password are set (`main.py:314-336`) | new per message (`:127-128`) |
| `SlackAdapter` | `gateways/slack.py:24` | `POST /api/gateway/slack/events` (`weebot/interfaces/web/routers/slack_webhook.py:33-68`), HMAC (`slack.py:48`) | lazily on first callback | new per message (`slack.py:122-125`) |
| `DiscordAdapter` | `gateways/discord.py:30` | `POST /api/gateway/discord/interactions` (`routers/discord_webhook.py:28-60`), Ed25519 (`discord.py:70-85`) | lazily | new per message |
| `WhatsAppAdapter` | `gateways/whatsapp.py:26` | `GET/POST /api/gateway/whatsapp/webhook` (`routers/whatsapp_webhook.py:35-79`), `X-Hub-Signature-256`, fail closed without app secret unless `whatsapp_allow_unsigned_webhooks` (`whatsapp.py:60-87`) | lazily | new per message |

Every adapter builds the flow the same way: `build_tools(role="admin")` then `create_flow(flow_type="plan_act", session, llm, tools, state_repo, profile_name)` from `weebot/interfaces/factories.py` (`telegram.py:222-230`, `slack.py:128-135`, `discord.py:188-195`, `whatsapp.py:115-122`, `signal.py:103-110`, `email.py:130-137`). Email also drops its own address and automated senders (`email.py:107-112`). The allowlist is edited with `python -m cli.main gateway allowlist ...` (`cli/commands/gateway.py:107-172`).

Consequences (read from source, not run):
- No adapter passes a mediator to `create_flow`, and `create_flow` does not default one (`factories.py:204-293`). `PlanningState` yields an error and returns when the mediator is None (`weebot/application/flows/states/planning.py:81-89`), so a gateway message cannot get a plan. (`PlanActFlowConfig.mediator` defaults to None, "required in practice", `weebot/application/models/plan_act_flow_config.py:90`.)
- No adapter passes an event bus: gateway runs publish nothing to the bus, so they reach no WebSocket and no bus journal.
- The flows resolve tools and collaborators through `shared_container()`, which in the web process is a second container next to the lifespan's (see `WebAPI.md`).
- Every allowlisted chat gets the `admin` tool role, which includes `bash`, `powershell` and `python_execute`; the web process approval channel is `FlowPauseApproval` (`main.py:197`), and no gateway has a way to answer a pause.
- `extract_media` turns any absolute path ending in a listed extension (including `.json`, `.yaml`, `.md`, `.txt`, `.csv`) in the agent's reply into an attachment (`base.py:214-243`); Telegram then opens and uploads that file (`telegram.py:281-288, 330-335`). The regex only matches paths starting with `/` (`base.py:72`), though the docstring names Windows paths (`:196`).
- Email authorizes on the `From` address (`email.py:114`); no sender-authentication check is in the file.
- Telegram loads the existing session inside `except Exception: pass` (`telegram.py:246-251`): a load error starts a fresh session with the same id. `/new` handled by the dispatcher only replies "will be reset" (`:262-263`); the reset itself happens only for the plain-text forms (`:211-220`).
- Slack, Discord, WhatsApp, Signal and email generate a new session id per message, so no conversation carries over.
- `handle_ponytail_command` imports `cli.commands.ponytail` (`base.py:158`), an interfaces module depending on the CLI package.

## Connected to
- **Built by** the web lifespan (`WebAPI.md`) and the platform webhook routers. **Uses** `create_flow`/`build_tools` (`CLI.md`), `GatewayAuth` (`weebot/core/gateway_auth.py`), `SafetyChecker` (`weebot/core/safety.py`), `GatewayFlowResolver` and `IGatewaySessionStorePort` (Telegram only, `main.py:274-279`).
- **Looks like but is not:** the generic `/api/webhook/run` (`routers/webhook.py`), which is not a `GatewayAdapter`; `atomic_mail` (agent-owned inbox tool), which is outbound/inbound mail as a tool, not a gateway.

## If you change this
**Hits:** every chat platform, the web lifespan startup, `gateway` CLI, tests `tests/unit/test_gateway_adapters.py`, `tests/unit/test_media_delivery.py`, `tests/unit/test_gateway_session.py`, `tests/unit/interfaces/test_discord_adapter.py`, `tests/unit/interfaces/gateways/test_discord_gateway_auth.py`, `tests/unit/interfaces/gateways/test_whatsapp_signature.py`, `tests/unit/fixes/test_w53_interface_roots.py`, `tests/unit/fixes/test_ssot_ponytail_modes.py`, `tests/unit/core/test_security_state_durability.py`, `tests/unit/test_latent_trap_fixes.py`, `tests/unit/test_rate_limit.py`.
**Does not hit:** the Web UI; the MCP server.

## Surfaces
Chat users on the six platforms; the admin who edits the allowlist.

## See
`weebot/interfaces/gateways/base.py`
