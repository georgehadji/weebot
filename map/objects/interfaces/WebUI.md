---
type: object
name: Web UI
code: weebot-ui (Next.js app router)
cluster: interfaces
universe: live
status: stale
verified: 2026-10-24
commit: 985d133d
---

# Web UI

The Next.js "Mission Center" in `weebot-ui/` (`npm run dev`, `weebot-ui/package.json` scripts; `next dev -H localhost` and `next start -H 127.0.0.1`, `weebot-ui/package.json:6, 8`). It talks to the FastAPI backend over REST (through a same-origin proxy) and WebSockets (direct to the backend).

## Why this shape
REST goes through `/api/...` on the Next server so the browser stays same-origin; the catch-all route handler forwards to the backend (`weebot-ui/src/app/api/[[...path]]/route.ts:4-45`). WebSockets cannot go through that handler, so they connect to the backend directly (`weebot-ui/next.config.mjs:26-27` comment, `src/lib/endpoints.ts:1-33`). Backend URLs live in one file, `src/lib/endpoints.ts`, from `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` (`:30-33`), overridable per browser by `localStorage` `weebot_backend_url` / `weebot_ws_url` (`src/lib/api.ts:3-12`, `src/providers/EventStreamProvider.tsx:70-84`). The API key is kept in `sessionStorage` `weebot_api_key` (`src/lib/api.ts:15-22`); `authHeaders()` and `withToken()` attach it to calls made outside `fetchApi` (`weebot-ui/src/lib/api.ts:24-35`).

## Shape
Pages (`src/app/`): `/` composer (`weebot-ui/src/app/(console)/page.tsx:17-27`), `/sessions` list, `/sessions/[id]` conversation (`weebot-ui/src/app/(console)/sessions/[id]/page.tsx`), `/ops` health, metrics, active sessions and a live log, `/models`, `/behavior` (monitor and settings tabs), `/settings` backend URLs, `/settings/behavior` redirect to `/behavior?tab=settings` (`settings/behavior/page.tsx:8-10`), `/debug` WebSocket tester. `layout.tsx:35-46` wraps all pages in Theme, Toast, `EventStreamProvider`, `AnnouncerProvider` and `ShellProvider`, and renders them inside `AppShell`.

## Frame and state (UI/UX plan, 2026-10-24)
- **One frame.** `AppShell` is the window (`h-dvh`): skip link, `AppBar` (the single 48 px header; below `lg` the nav and actions sit behind a menu `Dialog`), the only `<main id="main-content">`, and the command palette (`weebot-ui/src/components/shell/AppShell.tsx:17`, `AppBar.tsx:28`). A page fills the bar's title and connection slots, and names the session whose dock to show, with `useShellSlots` (`src/hooks/useShellSlots.ts:7`, `src/providers/ShellProvider.tsx:29`); pages own no chrome.
- **One console, mounted once.** The `(console)` route group holds `/` and `/sessions/[id]` under `app/(console)/layout.tsx`, which renders `ConsoleShell` (rail, content, dock; `src/components/shell/ConsoleShell.tsx:21`), so the rail and its data survive navigation. Below `md` the rail and dock are side sheets on the `Dialog` primitive (`ResponsivePanel`, `src/components/shell/ResponsivePanel.tsx:24`; `DialogSheet` in `src/components/ui/dialog.tsx`).
- **Async data is a type.** `Remote<T>` (`src/types/remote.ts`) is loaded by `useRemote` (`src/hooks/useRemote.ts`) and drawn by `StateView` (`src/components/common/StateView.tsx:24`): skeleton, error with Retry over stale data, empty, ready. `useSessionList` and `/sessions` use it (`src/hooks/useSessionList.ts:28`).
- **One status component.** `statusInfo` maps a status to label, icon and tone (`src/components/common/status.ts:43`); `StatusBadge` draws it, so status is never colour alone. Text colours use the `--status-*-fg` tokens, which meet 4.5:1 (`scripts/check_ui_contrast.py`).
- **Conversation.** `useStickToBottom` pins the timeline with an `IntersectionObserver` and counts unseen rows (`src/hooks/useStickToBottom.ts:14`); the timeline is a `role="log"` that is not a live region, and coarse moments go through `AnnouncerProvider` (`src/lib/announce.ts`). The composer is a reducer (`src/lib/composer.ts`) behind `useComposer` (`src/hooks/useComposer.ts`): never disabled while sending, per-session draft in `sessionStorage`, IME-safe Enter. Optimistic user messages carry `delivery` (`sending|sent|failed`); the server echo (same id) settles them and `markDelivery` records a failed send (`src/lib/session-reducer.ts:55, 107`). Tool rows show arguments, a failed state from the backend's `ToolEvent.is_error`, copy, and the full result on request.
- **Lazy heavy views.** reactflow loads on demand through `LazyPlanVisualizer`, recharts through `next/dynamic` in `/ops` (`src/components/plan/LazyPlanVisualizer.tsx`).
- **Backend facts the UI shows.** The session title is the stored one, else derived from the prompt (`weebot/domain/services/session_title.py`, `weebot/interfaces/web/routers/sessions.py` `_displayed_title`); `event_count` comes from `EventStorePort.count_events`; the planner's `TitleEvent` replaces the derived title (`weebot/application/services/task_runner.py`).

Backend calls:
- `src/lib/api.ts:104-197` (`fetchApi` adds `X-API-Key`): sessions list/create/get/events/delete/cancel/run/resume/input, models list/available, health check/ready/live, dashboard metrics, ops activeSessions/planViz/costSummary. Used: list, create+run on first message, input after that (`weebot-ui/src/hooks/useComposer.ts:68-74`), get+events (`weebot-ui/src/app/(console)/sessions/[id]/page.tsx:38-41`), cancel (`components/conversation/RunControls.tsx:24`), delete, models list, health, dashboard metrics, activeSessions, planViz, costSummary (`components/dock/CostTab.tsx:21`).
- Proxy (`route.ts`): target `BACKEND_URL` or `ENDPOINTS.api` (`:4`); forwards only `Content-Type` and `X-API-Key` (`:19-25`); always answers with `response.json()` (`:35-37`).
- Live events (`EventStreamProvider.tsx`): one socket per session to `{ws}/sessions/{id}?token=` (`:152-197`), reference-counted; after 5 failed reconnects falls back to `fetch` of `/api/events/stream` filtered by `session_id` client-side (`:106-150`). One global socket to `{ws}` for `session_presence` events only (`:234-267`), consumed by `useSessionPresence` / `useSessionList` (`src/hooks/useSessionPresence.ts`, `src/hooks/useSessionList.ts`).
- Behavior: socket `ENDPOINTS.behaviorWs` (`/api/behavior/ws`, or `/session/{id}`) with `withToken` (`weebot-ui/src/hooks/useBehavior.ts:60-65`); REST `trust`, `recent`, `override` direct to `ENDPOINTS.api` with `authHeaders()` (`:167-216`, `weebot-ui/src/components/behavior/RecentActions.tsx:51-59`); `app/behavior/page.tsx` calls only `/api/behavior/self-knowledge` through the proxy (`weebot-ui/src/app/behavior/page.tsx:93`). The settings tab has no settings API; it lists the environment variables (`:90-91`).
- `/ops` opens a socket to `{ws}` (with `withToken`) for its log view (`weebot-ui/src/app/ops/page.tsx:36-40, 61-77`).

Consequences (read from source, not run):
- The proxy forwards from the Next server, so the backend sees a loopback client. `require_mutation_identity` and `FailClosedMiddleware` exempt loopback (`weebot/interfaces/web/auth.py:211-218`, `weebot/interfaces/web/main.py:546-547`), and the Docker image binds the Next server on `0.0.0.0:3000` (`weebot-ui/Dockerfile:41-44`). `npm run dev` / `start` bind loopback only (F45), but with no `WEEBOT_API_KEY` any client that reaches port 3000 of the Docker image gets loopback rights on `/api/*`.
- The proxy parses every response as JSON (`route.ts:35`): SSE (`/api/chat/stream`, `/api/events/stream`) and text (`/api/health/prometheus`) come back as `null` through it. The SSE fallback avoids this only because it fetches `ENDPOINTS.api` directly.
- `/ops` "live log" listens on `/ws`, which only receives events without a `session_id` (`weebot/interfaces/web/event_broadcaster.py:39-43`), so it shows presence events, not session activity.
- Socket tokens go in the query string (`EventStreamProvider.tsx:174, 253`; `withToken`, `weebot-ui/src/lib/api.ts:31-35`, used by `useBehavior.ts:65`, `weebot-ui/src/app/ops/page.tsx:62`, `weebot-ui/src/hooks/useWebSocketDebug.ts:44`), the path the backend marks deprecated and logs (`weebot/interfaces/web/main.py:728-739`).
- `next.config.mjs:20-25` also rewrites `/api/:path*` to a hard-coded `http://localhost:8000`, a second routing rule beside the route handler that ignores `BACKEND_URL`.
- Backend endpoints with no UI caller: all of `/api/chat/*`, `/api/sessions/search`, `/api/sessions/{id}/steer`, `/api/sessions/{id}/resume` (`api.sessions.resume` is defined, unused), `/api/ponytail/*`, `/api/models/available`, `/api/health/ready` and `/live` (defined in `api.ts:169-170`, unused), behavior `watch/*`, `report/*`, `session/{id}`, `self-knowledge/regenerate`, `/api/webhook/run` (machine caller).

## Connected to
- **Calls** the Web API (`WebAPI.md`). **Owns** no backend state; per-browser settings only.
- **Types** mirror backend events in `src/types/events.ts`; the session reducer is `src/lib/session-reducer.ts`.
- **Looks like but is not:** the test page the backend serves at `/` (`weebot/interfaces/web/main.py:76-177, 599-602`).

## If you change this
**Hits:** every page; tests `weebot-ui/src/lib/endpoints.test.ts`, `src/lib/session-reducer.test.ts`, `src/hooks/useSessionEvents.test.ts`, `weebot-ui/tests/smoke.test.tsx` and the component, hook and lib tests beside their sources (vitest `**/*.test.{ts,tsx}`, `vitest.config.ts:9`), `src/components/ui/primitives.contract.test.tsx` (class selectors match what base-ui emits); browser tests in `weebot-ui/e2e/` (Playwright `testDir: ./e2e`, `playwright.config.ts:10`) run against a production build with every `/api` call and the socket stubbed (`e2e/fixtures.ts`): shell, conversation, lists, axe on seven routes in both themes at 375 and 1280 px, and the performance budgets (`e2e/perf.spec.ts`). `make lint-ui` ratchets UI debt (`scripts/lint_ui_debt.py`) and token contrast; ESLint enforces that `components/ui` imports only `@/lib/utils` and `lib/` imports no React (`weebot-ui/eslint.config.mjs`).
**Does not hit:** backend auth (enforced server side); the CLI.

## Surfaces
The operator in a browser on `localhost:3000`.

## See
`weebot-ui/src/lib/api.ts`, `weebot-ui/src/providers/EventStreamProvider.tsx`
