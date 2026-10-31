---
type: object
name: Web API (FastAPI)
code: create_app, lifespan
cluster: interfaces
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# Web API (FastAPI)

The HTTP and WebSocket backend, `python -m weebot.interfaces.web.main`. `create_app()` (`weebot/interfaces/web/main.py:404-693`) builds the app; `lifespan` (`main.py:181-401`) builds the container, the event fan-out, the scheduler and the long-polling gateways.

## Why this shape
The lifespan is the web process's composition root. It takes the process's `shared_container()` and stores it on `app.state.container` (`main.py:186-191`); routers resolve ports from it per request. Events reach browsers because the lifespan subscribes `WebSocketEventBroadcaster.publish` to the bus (`main.py:216-219`); nothing in the application layer knows a socket exists. The Mediator is warmed at boot (`container.warm_up()`, `main.py:237-241`) so the first `/sessions` request does not pay for it. Approvals pause the flow (`FlowPauseApproval`, `main.py:203`). The one API-key store is put on `app.state.api_key_store` (`main.py:207-209`). Shutdown drains `BackgroundTasks` before it closes the MCP toolkit, the key store and the DB pools (`main.py:378-398`).

## Shape
Middleware, in `create_app`, in the order added (the last one added is outermost): correlation id (`main.py:416-427`), CORS for `localhost:3000` plus `WEEBOT_CORS_ORIGIN` (`main.py:470-482`), `AuthMiddleware` when `weebot_api_key` or `web_require_auth` is set (`main.py:505-541`): every HTTP path except `_public_paths` goes through `auth.authenticate`; a refusal is 401 when a key was presented or one is expected (the legacy key, or store mode), else 503 for a remote caller with no key configured, `BodyLimitMiddleware` (1 MiB, `WEEBOT_MAX_BODY_BYTES`, `main.py:550-558`), and last, outermost, `RateLimitMiddleware` unless `WEEBOT_RATE_LIMIT_ENABLED` is off (`main.py:560-566`); it also counts 401/403 answers per client address and answers 429 after ten in a minute. `_public_paths` (`main.py:491-501`) is `/`, the health, live and prometheus probes, and the three platform callbacks, which verify their own signature.

Per-route auth lives in `weebot/interfaces/web/auth.py`: routes stamp and filter sessions with `current_principal` (`weebot/interfaces/web/auth.py:297-304`), the same rule the ownership checks use (`authenticate`); the sync `get_current_user_id` knows only the legacy key and no router may call it (audit R03, `tests/unit/fixes/test_r03_store_mode_principal.py`); `require_mutation_identity` (anonymous and non-loopback, or behind a proxy, is 403, `auth.py:276-289`), `verify_session_ownership` (404 on mismatch; skipped when the session has no `user_id` or `WEEBOT_ENFORCE_SESSION_OWNERSHIP` is off, `auth.py:239-273, 307-312`). In store mode a presented key resolves through `ApiKeyPort`, the store on `app.state` (`_key_store`, `_principal_from_key`, `auth.py:112-137`; hashing in `weebot/core/api_key_crypto.py`; `tests/unit/interfaces/web/test_auth_resolves_through_the_port.py`).

| Prefix | File | Endpoints | Auth deps |
|---|---|---|---|
| `/api/sessions` | `routers/sessions.py:29` | GET list, POST create, GET `/search`, GET `/{id}`, GET `/{id}/events`, DELETE, POST `/cancel`, `/resume`, `/run`, `/steer`, `/input` | mutations `require_mutation_identity`; reads by id `verify_session_ownership` |
| `/api/models` | `routers/models.py:24` | GET list, GET `/roles`, PUT and DELETE `/roles/{role}`, GET `/available` | PUT and DELETE `require_mutation_identity`; reads none |
| `/api/health` | `routers/health.py:35` | GET "", `/ready`, `/live`, `/prometheus`, `/metrics`, `/status` | none |
| `/api/dashboard` | `routers/dashboard.py:16` | GET `/metrics` | caller's sessions only (`routers/dashboard.py:37-38`) |
| `/api/behavior` | `routers/behavior_router.py:37` | GET trust, report, recent, session, watch/status, self-knowledge; POST override, watch/start, watch/stop, self-knowledge/regenerate; WS `/ws`, `/ws/session/{id}` | POSTs `require_mutation_identity`; GETs none |
| `/api/chat` | `routers/chat_router.py:35` | POST "", POST `/stream` (SSE), GET `/history`, GET `/{id}` | POSTs `require_mutation_identity`; `/{id}` ownership |
| `/api/events` | `routers/sse.py:26` | GET `/stream` (SSE, the caller's sessions' events and session-less ones) | ownership per session (`routers/sse.py:54-74`); the drop notice carries `id`, `session_id` and `timestamp` (`routers/sse.py:97-107`) |
| `/api/webhook` | `routers/webhook.py:26` | POST `/run` | `require_webhook_auth` (`routers/webhook.py:31-70`) |
| `/api/gateway/{discord,slack,whatsapp}` | `routers/discord_webhook.py:25`, `slack_webhook.py:31`, `whatsapp_webhook.py:33` | platform callbacks | platform signature |
| `/api` (ops) | `routers/ops_router.py:26` | GET `/sessions/active`, `/sessions/{id}/plan-viz`, `/costs/summary` | plan-viz ownership |
| `/api/ponytail` | `routers/ponytail.py:16` | GET `/mode`, POST `/mode/{mode}` | POST `require_mutation_identity` |
| root | `main.py:609-620` | GET `/metrics`, GET `/` (test HTML) | |

WebSockets: `/ws` (`main.py:623-647`) and `/ws/sessions/{id}` (`main.py:649-686`), both through `_websocket_auth` (`main.py:696-700`), which awaits the one rule `authenticate` (`weebot/interfaces/web/auth.py:198-236`) used by the HTTP middleware and the routes too: `X-API-Key`, `Authorization: Bearer`, subprotocol `bearer.<key>` (a `?token=` is refused, decision D2), resolved through the key store in store mode; no legacy key means a keyless caller gets in only from loopback. The handshake is answered with the marker subprotocol `weebot.v1`, never the key (`auth.py:32-33, 42-48`). The session socket also checks ownership (`main.py:659-672`), and identity is read from the same places (`auth.py:76-99`), so a browser socket is not anonymous. `WebSocketEventBroadcaster` sends an event to its session's sockets, and only events without a `session_id` to `/ws` (`weebot/interfaces/web/event_broadcaster.py:37-46`). `/ws` remembers each client's principal (`ConnectionManager.connect(principal=...)`, `main.py:635-637`), so a `SessionPresenceEvent` goes only to its `owner_user_id` when ownership is enforced (`broadcast_global(only_principal=...)`, `weebot/interfaces/web/websocket.py:154-163`; `event_broadcaster.py:51-57`). `DELETE /api/sessions/{id}` publishes a `deleted` presence frame (`routers/sessions.py:226, 231-242`).

Sessions: `/run` builds tools and a `TaskRunner` plan-act factory with the app's bus and steering (`routers/sessions.py:316-379`); `/input` and `/resume` go through `dispatch_session_input` (`routers/sessions.py:287-313, 421-451`, the shared `_dispatch_input` at `routers/sessions.py:454-494`).

Consequences (read from source, not run):
- One container per web process: the lifespan takes `shared_container()` (`main.py:186-191`), the same one `build_tools`, `create_flow` and the gateways resolve through (`weebot/interfaces/factories.py:56-72`), so the sub-agent flow factory's bus is the one the WebSocket broadcaster listens to (F55).
- A PlanActFlow built with no mediator stops at planning with an error (`weebot/application/flows/states/planning.py:95-103`); `build_flow` resolves the mediator and bus from the shared container when the caller passes none (`weebot/application/flows/flow_builder.py:114-125`), which covers `/api/webhook/run` (`routers/webhook.py:135-137`) and the chat gateways.
- `/api/webhook/run` continues a stored session only when its `user_id` is `webhook`, else 404 (F57, `routers/webhook.py:113-123`); it runs under `DenyApproval`, since a webhook caller cannot answer a prompt (`routers/webhook.py:138-140`).
- Fixed (W2.1, 2026-10-28): store-mode principal keys pass the HTTP middleware and open sockets; both used to compare only against `weebot_api_key` (`tests/unit/fixes/test_w21_one_authenticator.py`).
- `/api/costs/summary` has no tenant filter (`routers/ops_router.py:85-102`). Fixed (F58): `/api/sessions/search` keeps only the caller's sessions (`routers/sessions.py:154-161`), `/api/dashboard/metrics` counts only the caller's (`routers/dashboard.py:37-38`), `/api/events/stream` forwards only events of the caller's sessions (`routers/sse.py:54-74`).
- `watch/start` starts a file watcher only on an existing folder inside `WORKSPACE_ROOT`, for a session the caller owns, once `require_mutation_identity` passes; a refusal does not echo the path (`routers/behavior_router.py:180-205`).
- The behavior sockets use the same `authenticate` rule through `_ws_authorized` (`behavior_router.py:305-309`). The session routes and the session socket check ownership through `_require_owner` (`behavior_router.py:98-100`; the socket closes 4003), and `/ws` sends each client only its own sessions' events (`behavior_router.py:276-281`). `/trust` and `/report` stay global (decision D-BEH).
- Silent swallow: `cancel` falls back on `except (KeyError, Exception)` with no log (`routers/sessions.py:273-276`).
- Slack and WhatsApp callbacks spawn their work on the background-task owner (`routers/slack_webhook.py:68`, `routers/whatsapp_webhook.py:78`), which the lifespan drains at shutdown (`main.py:380-382`).
- `/app` static mount looks for `weebot-ui/dist` (`main.py:688-691`); the UI builds `output: 'standalone'` (`weebot-ui/next.config.mjs:12`), so the mount is inert.
- `ponytail` router imports from `cli.commands.ponytail` (`routers/ponytail.py:13`), an interfaces module reaching into the CLI package.

## Connected to
- **Owns** `app.state.container`, `app.state.scheduler` (`main.py:249-259`), `app.state.api_key_store` (`main.py:207-209`), the Telegram, Signal and email adapters (`main.py:280-352`), lazily the Discord, Slack and WhatsApp adapters (`routers/*_webhook.py`).
- **Uses** the Event bus (`infrastructure/EventBus.md`), Mediator (`application/Mediator.md`), `TaskRunner`, `SQLiteStateRepository`, session deletion orchestrator (`weebot/interfaces/web/dependencies.py:26-75`).
- **Called by** the Web UI (`WebUI.md`).
- **Looks like but is not:** the MCP server's SSE transport (`MCPServer.md`), a separate process on port 8765.

## If you change this
**Hits:** the Web UI, chat gateways started in the lifespan, tests `tests/unit/interfaces/web/` (`test_auth_resolves_through_the_port.py`, `test_chat_stream_endpoint.py`, `test_d26_broadcast_liveness.py`, `test_event_broadcaster_wiring.py`, `test_ponytail_router.py`, `test_resume_session_endpoint.py`, `test_run_session_endpoint.py`, `test_session_deletion_wiring.py`, `test_session_response.py`, `test_steer_endpoint.py`, `test_web_auth_default.py`, `test_webhook_router_security.py`), `tests/unit/interfaces/test_w6_ws_authorisation.py`, `tests/unit/interfaces/test_discord_adapter.py`, `tests/unit/fixes/test_f22_ops_router_dispatch.py`, `tests/unit/fixes/test_w52_mediator_dispatch.py`, `tests/unit/fixes/test_cron_agent_jobs_wired.py`, `tests/unit/fixes/test_ssot_ponytail_modes.py`, `tests/unit/fixes/test_ssot_version.py`, `tests/unit/test_defect_d1_websocket_failopen.py`, `tests/unit/test_regression_websocket_race.py`, `tests/unit/test_rate_limit.py`, `tests/unit/test_session_id_validation.py`, `tests/unit/test_bounded_drop_oldest_queue.py`, `tests/unit/test_behavior_ledger_git.py`, `tests/unit/test_audit_findings.py`, `tests/unit/test_low_priority.py`.
**Does not hit:** the CLI's container; the MCP server.

## Surfaces
The Next.js UI, chat platforms (webhooks), automation callers (`/api/webhook/run`), Prometheus (`/metrics`, `/api/health/prometheus`).

## See
`weebot/interfaces/web/main.py`, `weebot/interfaces/web/auth.py`
