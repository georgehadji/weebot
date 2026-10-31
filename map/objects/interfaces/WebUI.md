---
type: object
name: Web UI
code: weebot-ui (Next.js app router)
cluster: interfaces
universe: live
status: verified
verified: 2026-10-31
commit: 7d205bb1
---

# Web UI

The Next.js "Mission Center" in `weebot-ui/` (`npm run dev`, `weebot-ui/package.json` scripts; `next dev -H localhost` and `next start -H 127.0.0.1`, `weebot-ui/package.json:6, 8`). It talks to the FastAPI backend over REST (through a same-origin proxy) and WebSockets (direct to the backend).

## Why this shape
REST goes through `/api/...` on the Next server so the browser stays same-origin; the catch-all route handler forwards to the backend (`weebot-ui/src/app/api/[[...path]]/route.ts:5-55`). WebSockets cannot go through that handler, so they connect to the backend directly (`weebot-ui/next.config.mjs:29-30` comment, `src/lib/endpoints.ts:1-33`). Backend URLs live in one file, `src/lib/endpoints.ts`, from `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` (`:30-33`), overridable per browser by `localStorage` `weebot_backend_url` / `weebot_ws_url` (`src/lib/api.ts:3-13`, `src/providers/EventStreamProvider.tsx:84-98`). The API key is kept in `sessionStorage` `weebot_api_key` (`src/lib/api.ts:15-23`); `authHeaders()` attaches it to calls made outside `fetchApi` (`weebot-ui/src/lib/api.ts:25-29`), and `openSocket()` sends it as a WebSocket subprotocol (`:31-38`).

## Shape
Pages (`src/app/`): `/` composer (`weebot-ui/src/app/(console)/page.tsx:16-27`), `/sessions` list, `/sessions/[id]` conversation (`weebot-ui/src/app/(console)/sessions/[id]/page.tsx`), `/ops` health, metrics, active sessions and a live log, `/models`, `/behavior` (monitor and settings tabs), `/settings` backend URLs, `/settings/behavior` redirect to `/behavior?tab=settings` (`settings/behavior/page.tsx:8-10`), `/debug` WebSocket tester. `layout.tsx:35-47` wraps all pages in Theme, Toast, `EventStreamProvider`, a tooltip provider, `AnnouncerProvider` and `ShellProvider`, and renders them inside `AppShell`.

## Frame and state (UI/UX plan, 2026-10-24)
- **One frame.** `AppShell` is the window (`h-dvh`): skip link, `AppBar` (the single 48 px header; below `lg` the nav and actions sit behind a menu `Dialog`), the only `<main id="main-content">`, and the command palette (`weebot-ui/src/components/shell/AppShell.tsx:17`, `AppBar.tsx:28`). A page fills the bar's title and connection slots, and names the session whose dock to show, with `useShellSlots` (`src/hooks/useShellSlots.ts:7`, `src/providers/ShellProvider.tsx:29`); pages own no chrome.
- **One console, mounted once.** The `(console)` route group holds `/` and `/sessions/[id]` under `app/(console)/layout.tsx`, which renders `ConsoleShell` (rail, content, dock; `src/components/shell/ConsoleShell.tsx:21`), so the rail and its data survive navigation. Below `md` the rail and dock are side sheets on the `Dialog` primitive (`ResponsivePanel`, `src/components/shell/ResponsivePanel.tsx:24`; `DialogSheet` in `src/components/ui/dialog.tsx`).
- **Async data is a type.** `Remote<T>` (`src/types/remote.ts`) is loaded by `useRemote` (`src/hooks/useRemote.ts`) and drawn by `StateView` (`src/components/common/StateView.tsx:24`): skeleton, error with Retry over stale data, empty, ready. `useSessionList` and `/sessions` use it (`src/hooks/useSessionList.ts:28`).
- **One status component.** `statusInfo` maps a status to label, icon and tone (`src/components/common/status.ts:43`); `StatusBadge` draws it, so status is never colour alone. Text colours use the `--status-*-fg` tokens, which meet 4.5:1 (`scripts/check_ui_contrast.py`).
- **Conversation.** `useStickToBottom` pins the timeline with an `IntersectionObserver` and counts unseen rows (`src/hooks/useStickToBottom.ts:14`); the timeline is a `role="log"` that is not a live region, and coarse moments go through `AnnouncerProvider` (`src/lib/announce.ts`). The composer is a reducer (`src/lib/composer.ts`) behind `useComposer` (`src/hooks/useComposer.ts`): never disabled while sending, per-session draft in `sessionStorage`, IME-safe Enter. Optimistic user messages carry `delivery` (`sending|sent|failed`); the server echo (same id) settles them and `markDelivery` records a failed send (`src/lib/session-reducer.ts:55, 107`). Tool rows show arguments, a failed state from the backend's `ToolEvent.is_error`, copy, and the full result on request.
- **Lazy heavy views.** reactflow loads on demand through `LazyPlanVisualizer`, recharts through `next/dynamic` in `/ops` (`src/components/plan/LazyPlanVisualizer.tsx`).
- **Backend facts the UI shows.** The session title is the stored one, else derived from the prompt (`weebot/domain/services/session_title.py`, `weebot/interfaces/web/routers/sessions.py` `_displayed_title`); `event_count` comes from `EventStorePort.count_events`; the planner's `TitleEvent` replaces the derived title (`weebot/application/services/task_runner.py`).

Backend calls:
- `src/lib/api.ts:40-82, 117-218` (`fetchApi` adds `X-API-Key`): sessions list/create/get/events/delete/cancel/run/resume/input, models list/available/roles/setRole/resetRole, health check/ready/live, dashboard metrics, ops activeSessions/planViz/costSummary. Used: list, create+run on first message, input after that (`weebot-ui/src/hooks/useComposer.ts:76-88`), get+events (`weebot-ui/src/app/(console)/sessions/[id]/page.tsx:43-57`), cancel (`components/conversation/RunControls.tsx:24`), delete, models list, per-role model picks (`components/models/RoleModelsPanel.tsx:91-97`), health, dashboard metrics, activeSessions, planViz, costSummary (`components/dock/CostTab.tsx:21`).
- Proxy (`route.ts`): target `BACKEND_URL` or `ENDPOINTS.api` (`:5`); refuses a non-same-origin POST/PUT/PATCH/DELETE with 403 (`:17-19`, policy in `lib/proxy-guard.ts`); forwards the client's `Content-Type`, `X-API-Key` and `Authorization` (`:25-36`); always answers with `response.json()` (`:45-47`).
- Live events (`EventStreamProvider.tsx`): one socket per session to `{ws}/sessions/{id}`, the key sent as the `bearer.<key>` subprotocol by `openSocket` (`src/lib/api.ts:36-38`), not in the URL (`:181-226`), reference-counted; after 5 failed reconnects falls back to `fetch` of `/api/events/stream` filtered by `session_id` client-side (`:120-179`). One global socket to `{ws}` for `session_presence` events only (`:263-296`), consumed by `useSessionPresence` / `useSessionList` (`src/hooks/useSessionPresence.ts`, `src/hooks/useSessionList.ts`).
- Behavior: socket `ENDPOINTS.behaviorWs` (`/api/behavior/ws`, or `/session/{id}`) with `openSocket` (`weebot-ui/src/hooks/useBehavior.ts:69-74`); REST `trust`, `recent`, `override` through `getApiBase()` (the proxy unless a backend URL is set) with `authHeaders()` (`:184-229`), while `RecentActions.tsx` posts `override` direct to `ENDPOINTS.api` (`weebot-ui/src/components/behavior/RecentActions.tsx:51-59`); `app/behavior/page.tsx` calls only `/api/behavior/self-knowledge` through the proxy (`weebot-ui/src/app/behavior/page.tsx:96`). The settings tab has no settings API; it lists the environment variables (`:93-94, 132-141`).
- `/ops` opens a socket to `{ws}` (with `openSocket`) for its log view (`weebot-ui/src/app/ops/page.tsx:37-41, 68-84`).

Consequences (read from source, not run):
- The proxy forwards from the Next server, so the backend sees a loopback client. `authenticate` admits a loopback caller as anonymous when no key is configured (`weebot/interfaces/web/auth.py:236`), and `require_mutation_identity` lets an anonymous loopback caller mutate unless `WEEBOT_BEHIND_PROXY` is on, which is off by default (`auth.py:55-64, 276-289`; `.env.example:189`). The Docker image binds the Next server on `0.0.0.0:3000` (`weebot-ui/Dockerfile:41-44`). `npm run dev` / `start` bind loopback only (F45), but with no `WEEBOT_API_KEY` and that flag off, any client that reaches port 3000 of the Docker image gets loopback rights on `/api/*`.
- The proxy parses every response as JSON (`route.ts:45`): SSE (`/api/chat/stream`, `/api/events/stream`) and text (`/api/health/prometheus`) come back as `null` through it. The SSE fallback avoids this only because it fetches `ENDPOINTS.api` directly.
- `/ops` "live log" listens on `/ws`, which only receives events without a `session_id` (`weebot/interfaces/web/event_broadcaster.py:37-43`), so it shows presence events, not session activity.
- Socket keys travel as the `bearer.<key>` subprotocol, not the query string: every socket opens through `openSocket` (`EventStreamProvider.tsx:189, 268`, `useBehavior.ts:74`, `weebot-ui/src/app/ops/page.tsx:69`, `weebot-ui/src/hooks/useWebSocketDebug.ts:44`). The backend refuses a `?token=` (decision D2, `weebot/interfaces/web/auth.py:76-99`). The SSE fallback sends `X-API-Key` (`EventStreamProvider.tsx:128-131`).
- `next.config.mjs:23-28` also rewrites `/api/:path*` to a hard-coded `http://localhost:8000`, a second routing rule beside the route handler that ignores `BACKEND_URL`.
- Backend endpoints with no UI caller: all of `/api/chat/*`, `/api/sessions/search`, `/api/sessions/{id}/steer`, `/api/sessions/{id}/resume` (`api.sessions.resume` is defined, unused), `/api/ponytail/*`, `/api/models/available`, `/api/health/ready` and `/live` (defined in `api.ts:182-183`, unused), behavior `watch/*`, `report/*`, `session/{id}`, `self-knowledge/regenerate`, `/api/webhook/run` (machine caller).

## Connected to
- **Calls** the Web API (`WebAPI.md`). **Owns** no backend state; per-browser settings only.
- **Types** mirror backend events in `src/types/events.ts`; the session reducer is `src/lib/session-reducer.ts`.
- **Looks like but is not:** the test page the backend serves at `/` (`weebot/interfaces/web/main.py:76-177, 617-620`).

## If you change this
**Hits:** every page; tests `weebot-ui/src/lib/endpoints.test.ts`, `src/lib/session-reducer.test.ts`, `src/hooks/useSessionEvents.test.ts`, `weebot-ui/tests/smoke.test.tsx` and the component, hook and lib tests beside their sources (vitest `**/*.test.{ts,tsx}`, `vitest.config.ts:9`), `src/components/ui/primitives.contract.test.tsx` (class selectors match what base-ui emits); browser tests in `weebot-ui/e2e/` (Playwright `testDir: ./e2e`, `playwright.config.ts:10`) run against a production build with every `/api` call and the socket stubbed (`e2e/fixtures.ts`): shell, conversation, lists, axe on seven routes in both themes at 375 and 1280 px, and the performance budgets (`e2e/perf.spec.ts`). `make lint-ui` ratchets UI debt (`scripts/lint_ui_debt.py`) and token contrast; ESLint enforces that `components/ui` imports only `@/lib/utils` and `lib/` imports no React (`weebot-ui/eslint.config.mjs`).
**Does not hit:** backend auth (enforced server side); the CLI.

## Surfaces
The operator in a browser on `localhost:3000`.

## See
`weebot-ui/src/lib/api.ts`, `weebot-ui/src/providers/EventStreamProvider.tsx`
