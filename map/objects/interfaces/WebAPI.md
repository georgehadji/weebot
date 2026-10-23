---
type: object
name: Web API (FastAPI)
code: create_app, lifespan
cluster: interfaces
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# Web API (FastAPI)

The HTTP and WebSocket backend, `python -m weebot.interfaces.web.main`. `create_app()` (`weebot/interfaces/web/main.py:392-662`) builds the app; `lifespan` (`:179-385`) builds the container, the event fan-out, the scheduler and the long-polling gateways.

## Why this shape
The lifespan is the web process's composition root. It builds one `Container` and stores it on `app.state.container` (`:183-185`); routers resolve ports from it per request. Events reach browsers because the lifespan subscribes `WebSocketEventBroadcaster.publish` to the bus (`:205-208`); nothing in the application layer knows a socket exists. The Mediator is warmed at boot (`:222-226`) so the first `/sessions` request does not pay for it. Approvals pause the flow (`FlowPauseApproval`, `:197`).

## Shape
Middleware, in `create_app`: correlation id (`:405-415`), `RateLimitMiddleware` unless `WEEBOT_RATE_LIMIT_ENABLED` is off (`:420-426`), CORS for `localhost:3000` plus `WEEBOT_CORS_ORIGIN` (`:464-475`), then either `APIKeyMiddleware` (when `weebot_api_key` is set: `X-API-Key` on every HTTP path except `/api/health`, `/`, `/api/prometheus`, `:482-504`) or `FailClosedMiddleware` (when `web_require_auth`: non-loopback gets 503 except `/api/health`, `/api/live`, `/`, `/api/prometheus`, `:505-540`).

Per-route auth lives in `weebot/interfaces/web/auth.py`: `get_current_user_id` (legacy key compare, else `"anonymous"`, `:49-104`), `require_mutation_identity` (anonymous and non-loopback is 403, `:192-205`), `verify_session_ownership` (404 on mismatch; skipped when the session has no `user_id` or `WEEBOT_ENFORCE_SESSION_OWNERSHIP` is off, `:155-189, 255-257`).

| Prefix | File | Endpoints | Auth deps |
|---|---|---|---|
| `/api/sessions` | `routers/sessions.py:27` | GET list, POST create, GET `/search`, GET `/{id}`, GET `/{id}/events`, DELETE, POST `/cancel`, `/resume`, `/run`, `/steer`, `/input` | mutations `require_mutation_identity`; reads by id `verify_session_ownership` |
| `/api/models` | `routers/models.py:20` | GET list, GET `/available` | none |
| `/api/health` | `routers/health.py:35` | GET "", `/ready`, `/live`, `/prometheus`, `/metrics`, `/status` | none |
| `/api/dashboard` | `routers/dashboard.py:15` | GET `/metrics` | none |
| `/api/behavior` | `routers/behavior_router.py:26` | GET trust, report, recent, session, watch/status, self-knowledge; POST override, watch/start, watch/stop, self-knowledge/regenerate; WS `/ws`, `/ws/session/{id}` | none on POSTs |
| `/api/chat` | `routers/chat_router.py:35` | POST "", POST `/stream` (SSE), GET `/history`, GET `/{id}` | POSTs `require_mutation_identity`; `/{id}` ownership |
| `/api/events` | `routers/sse.py:24` | GET `/stream` (SSE, every event on the bus) | none |
| `/api/webhook` | `routers/webhook.py:26` | POST `/run` | `require_webhook_auth` (`:31-70`) |
| `/api/gateway/{discord,slack,whatsapp}` | `routers/discord_webhook.py:25`, `slack_webhook.py:30`, `whatsapp_webhook.py:32` | platform callbacks | platform signature |
| `/api` (ops) | `routers/ops_router.py:26` | GET `/sessions/active`, `/sessions/{id}/plan-viz`, `/costs/summary` | plan-viz ownership |
| `/api/ponytail` | `routers/ponytail.py:15` | GET `/mode`, POST `/mode/{mode}` | none |
| root | `main.py:580-591` | GET `/metrics`, GET `/` (test HTML) | |

WebSockets: `/ws` (`main.py:594-616`) and `/ws/sessions/{id}` (`:618-655`), both through `_websocket_auth` (`:665-715`: subprotocol `bearer.<key>`, `Authorization`, then deprecated `?token=`; no key means loopback only). The session socket also checks ownership (`:632-641`). `WebSocketEventBroadcaster` sends an event to its session's sockets, and only events without a `session_id` to `/ws` (`weebot/interfaces/web/event_broadcaster.py:37-43`).

Sessions: `/run` builds tools and a `TaskRunner` plan-act factory with the app's bus and steering (`routers/sessions.py:275-307`); `/input` and `/resume` go through `dispatch_session_input` (`:385-425`).

Consequences (read from source, not run):
- Two containers per web process. The lifespan builds `Container()` (`main.py:183`), but `build_tools` and `create_flow` resolve through `shared_container()` (`weebot/interfaces/factories.py:65-87`), which nothing in the web process seeds (no other writer of `_shared_container`). Tool wiring, guard chain and the sub-agent flow factory's event bus (`factories.py:324-325`) come from the second container, whose bus the WebSocket broadcaster does not listen to.
- Every PlanActFlow built with no mediator stops at planning with an error (`weebot/application/flows/states/planning.py:81-89`). `/api/webhook/run` builds one that way (`routers/webhook.py:125-132`), as do all chat gateways.
- `/api/webhook/run` with a `session_id` loads and continues any stored session, with no ownership check (`routers/webhook.py:114-117`), and runs it with no event bus (`:125-132`).
- The middleware exemptions name routes that do not exist: `/api/live` and `/api/prometheus` (`main.py:489, 517`); the real ones are `/api/health/live` and `/api/health/prometheus` (`routers/health.py:305, 312`), so a remote liveness probe or scrape needs the key.
- With `WEEBOT_API_KEY` set, `APIKeyMiddleware` also covers `/api/gateway/*` (`main.py:489`), whose callers (Discord, Slack, Meta) cannot send `X-API-Key`.
- Store-mode principal keys cannot pass the HTTP middleware: it compares only against `weebot_api_key` (`main.py:495`), and with no key `FailClosedMiddleware` refuses non-loopback (`:520-533`).
- Reads with no tenant filter: `/api/sessions/search` (`routers/sessions.py:106-117`), `/api/events/stream` (`routers/sse.py:231-292`), `/api/dashboard/metrics` (`routers/dashboard.py:35`).
- Behavior POSTs have no `require_mutation_identity` (`routers/behavior_router.py:123-196`); `watch/start` starts a file watcher on any existing directory the caller names (`:135-157`). `/api/ponytail/mode/{mode}` writes global mode with no identity check (`routers/ponytail.py:26-33`).
- The behavior sockets do their own auth: with no API key both accept any client, loopback or not (`behavior_router.py:253-284, 365-372`), unlike `_websocket_auth` (`main.py:678-680`); `/ws/session/{id}` accepts only `?token=` and checks no ownership.
- Silent swallows: `cancel` falls back on `except (KeyError, Exception)` with no log (`routers/sessions.py:204-207`); browser pool close `except Exception: pass` (`main.py:369-370`); `touch_last_used` (`auth.py:138-139, 237-238`).
- Slack and WhatsApp callbacks spawn `asyncio.create_task` with no reference kept (`routers/slack_webhook.py:163`, `routers/whatsapp_webhook.py:293`).
- `/app` static mount looks for `weebot-ui/dist` (`main.py:658-660`); the UI builds `output: 'standalone'` (`weebot-ui/next.config.mjs:9`), so the mount is inert.
- `ponytail` router imports from `cli.commands.ponytail` (`routers/ponytail.py:13`), an interfaces module reaching into the CLI package.

## Connected to
- **Owns** `app.state.container`, `app.state.scheduler` (`main.py:234-244`), the Telegram, Signal and email adapters (`:261-336`), lazily the Discord, Slack and WhatsApp adapters (`routers/*_webhook.py`).
- **Uses** the Event bus (`infrastructure/EventBus.md`), Mediator (`application/Mediator.md`), `TaskRunner`, `SQLiteStateRepository`, session deletion orchestrator (`weebot/interfaces/web/dependencies.py:300-324`).
- **Called by** the Web UI (`WebUI.md`).
- **Looks like but is not:** the MCP server's SSE transport (`MCPServer.md`), a separate process on port 8765.

## If you change this
**Hits:** the Web UI, chat gateways started in the lifespan, tests `tests/unit/interfaces/web/` (`test_chat_stream_endpoint.py`, `test_d26_broadcast_liveness.py`, `test_event_broadcaster_wiring.py`, `test_ponytail_router.py`, `test_resume_session_endpoint.py`, `test_run_session_endpoint.py`, `test_session_deletion_wiring.py`, `test_session_response.py`, `test_steer_endpoint.py`, `test_web_auth_default.py`, `test_webhook_router_security.py`), `tests/unit/interfaces/test_w6_ws_authorisation.py`, `tests/unit/interfaces/test_discord_adapter.py`, `tests/unit/fixes/test_f22_ops_router_dispatch.py`, `tests/unit/fixes/test_w52_mediator_dispatch.py`, `tests/unit/fixes/test_cron_agent_jobs_wired.py`, `tests/unit/fixes/test_ssot_ponytail_modes.py`, `tests/unit/fixes/test_ssot_version.py`, `tests/unit/test_defect_d1_websocket_failopen.py`, `tests/unit/test_regression_websocket_race.py`, `tests/unit/test_rate_limit.py`, `tests/unit/test_session_id_validation.py`, `tests/unit/test_bounded_drop_oldest_queue.py`, `tests/unit/test_behavior_ledger_git.py`, `tests/unit/test_audit_findings.py`, `tests/unit/test_low_priority.py`.
**Does not hit:** the CLI's container; the MCP server.

## Surfaces
The Next.js UI, chat platforms (webhooks), automation callers (`/api/webhook/run`), Prometheus (`/metrics`, `/api/health/prometheus`).

## See
`weebot/interfaces/web/main.py`, `weebot/interfaces/web/auth.py`
