---
type: object
name: Web UI
code: weebot-ui (Next.js app router)
cluster: interfaces
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# Web UI

The Next.js "Mission Center" in `weebot-ui/` (`npm run dev`, `weebot-ui/package.json` scripts). It talks to the FastAPI backend over REST (through a same-origin proxy) and WebSockets (direct to the backend).

## Why this shape
REST goes through `/api/...` on the Next server so the browser stays same-origin; the catch-all route handler forwards to the backend (`weebot-ui/src/app/api/[[...path]]/route.ts:4-45`). WebSockets cannot go through that handler, so they connect to the backend directly (`weebot-ui/next.config.mjs:26-27` comment, `src/lib/endpoints.ts:1-33`). Backend URLs live in one file, `src/lib/endpoints.ts`, from `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` (`:30-33`), overridable per browser by `localStorage` `weebot_backend_url` / `weebot_ws_url` (`src/lib/api.ts:3-12`, `src/providers/EventStreamProvider.tsx:70-84`). The API key is kept in `sessionStorage` `weebot_api_key` (`src/lib/api.ts:15-22`).

## Shape
Pages (`src/app/`): `/` composer (`page.tsx:16-27`), `/sessions` list, `/sessions/[id]` conversation, `/ops` health, metrics, active sessions and a live log, `/models`, `/behavior` (monitor and settings tabs), `/settings` backend URLs, `/settings/behavior` redirect to `/behavior?tab=settings` (`settings/behavior/page.tsx:8-10`), `/debug` WebSocket tester. `layout.tsx:33-44` wraps all pages in Theme, Toast and `EventStreamProvider`.

Backend calls:
- `src/lib/api.ts:91-184` (`fetchApi` adds `X-API-Key`): sessions list/create/get/events/delete/cancel/run/resume/input, models list/available, health check/ready/live, dashboard metrics, ops activeSessions/planViz/costSummary. Used: list, create+run on first message, input after that (`components/conversation/Composer.tsx:97-103`), get+events (`app/sessions/[id]/page.tsx:39-42`), cancel (`components/conversation/RunControls.tsx:24`), delete, models list, health, dashboard metrics, activeSessions, planViz, costSummary (`components/dock/CostTab.tsx:21`).
- Proxy (`route.ts`): target `BACKEND_URL` or `ENDPOINTS.api` (`:4`); forwards only `Content-Type` and `X-API-Key` (`:19-25`); always answers with `response.json()` (`:35-37`).
- Live events (`EventStreamProvider.tsx`): one socket per session to `{ws}/sessions/{id}?token=` (`:152-197`), reference-counted; after 5 failed reconnects falls back to `fetch` of `/api/events/stream` filtered by `session_id` client-side (`:106-150`). One global socket to `{ws}` for `session_presence` events only (`:234-267`), consumed by `useSessionPresence` / `useSessionList` (`src/hooks/useSessionPresence.ts`, `src/hooks/useSessionList.ts`).
- Behavior: socket `ENDPOINTS.behaviorWs` (`/api/behavior/ws`, or `/session/{id}`) (`src/hooks/useBehavior.ts:58-64`); REST `trust`, `recent`, `override` direct to `ENDPOINTS.api` (`:166-215`, `components/behavior/RecentActions.tsx:50-56`); `app/behavior/page.tsx` uses `/api/behavior/settings` and `/api/behavior/self-knowledge` through the proxy (`:96, 110, 127`).
- `/ops` opens a raw socket to `{ws}` for its log view (`app/ops/page.tsx:35-70`).

Consequences (read from source, not run):
- `/api/behavior/settings` (GET and POST, `app/behavior/page.tsx:96, 110`) has no backend route; the behavior router defines none (`weebot/interfaces/web/routers/behavior_router.py:77-196`). Load falls back to defaults silently; save never succeeds.
- The proxy forwards from the Next server, so the backend sees a loopback client. `require_mutation_identity` and `FailClosedMiddleware` exempt loopback (`weebot/interfaces/web/auth.py:198-205`, `weebot/interfaces/web/main.py:520-521`), and the Docker image binds the Next server on `0.0.0.0:3000` (`weebot-ui/Dockerfile:41-44`). With no `WEEBOT_API_KEY`, any client that reaches port 3000 gets loopback rights on `/api/*`.
- The proxy parses every response as JSON (`route.ts:35`): SSE (`/api/chat/stream`, `/api/events/stream`) and text (`/api/health/prometheus`) come back as `null` through it. The SSE fallback avoids this only because it fetches `ENDPOINTS.api` directly.
- Behavior REST calls and the behavior socket send no API key (`useBehavior.ts:64, 175, 193, 205-209`, `RecentActions.tsx:56`), nor does the `/ops` socket (`ops/page.tsx:61`) or `/debug` (`hooks/useWebSocketDebug.ts:39-43`). With `WEEBOT_API_KEY` set they get 401 / close 4001.
- `/ops` "live log" listens on `/ws`, which only receives events without a `session_id` (`weebot/interfaces/web/event_broadcaster.py:39-43`), so it shows presence events, not session activity.
- Socket tokens go in the query string (`EventStreamProvider.tsx:159, 238`), the path the backend marks deprecated and logs (`main.py:701-713`).
- `next.config.mjs:20-25` also rewrites `/api/:path*` to a hard-coded `http://localhost:8000`, a second routing rule beside the route handler that ignores `BACKEND_URL`.
- Backend endpoints with no UI caller: all of `/api/chat/*`, `/api/sessions/search`, `/api/sessions/{id}/steer`, `/api/sessions/{id}/resume` (`api.sessions.resume` is defined, unused), `/api/ponytail/*`, `/api/models/available`, `/api/health/ready` and `/live` (defined in `api.ts:148-149`, unused), behavior `watch/*`, `report/*`, `session/{id}`, `self-knowledge/regenerate`, `/api/webhook/run` (machine caller).

## Connected to
- **Calls** the Web API (`WebAPI.md`). **Owns** no backend state; per-browser settings only.
- **Types** mirror backend events in `src/types/events.ts`; the session reducer is `src/lib/session-reducer.ts`.
- **Looks like but is not:** the test page the backend serves at `/` (`main.py:75-176, 588-591`).

## If you change this
**Hits:** every page; tests `weebot-ui/src/lib/endpoints.test.ts`, `src/lib/session-reducer.test.ts`, `src/hooks/useSessionEvents.test.ts`, `weebot-ui/tests/smoke.test.tsx` (vitest `**/*.test.{ts,tsx}`, `vitest.config.ts:9`; Playwright `testDir: ./tests`, `playwright.config.ts:4`). Backend tests do not cover the UI.
**Does not hit:** backend auth (enforced server side); the CLI.

## Surfaces
The operator in a browser on `localhost:3000`.

## See
`weebot-ui/src/lib/api.ts`, `weebot-ui/src/providers/EventStreamProvider.tsx`
