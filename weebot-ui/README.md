# Weebot UI

Web-based user interface for the Weebot AI Agent Framework.

## Tech Stack

- [Next.js 16](https://nextjs.org/) (App Router)
- [React 19](https://react.dev/)
- [TypeScript](https://www.typescriptlang.org/)
- [Tailwind CSS](https://tailwindcss.com/)
- [shadcn/ui](https://ui.shadcn.com/) components
- [Recharts](https://recharts.org/) for dashboard visualizations
- [Monaco Editor](https://microsoft.github.io/monaco-editor/) for code display
- [Lucide](https://lucide.dev/) icons

## Getting Started

```bash
cd weebot-ui
npm install
npm run dev
```

The dev server starts on [http://localhost:3000](http://localhost:3000). It connects to the Weebot API at `http://localhost:8000`.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Development server with hot reload |
| `npm run build` | Production build |
| `npm run start` | Serve production build |
| `npm run lint` | Run ESLint (also enforces the layer rules below) |
| `npm test` | Unit and component tests (vitest) |
| `npm run test:e2e` | Browser tests (Playwright): shell, conversation, lists, accessibility (axe), performance budgets |

`npm run test:e2e` builds the app into `.next-e2e/` and serves it on port 3100 (`e2e/serve.mjs`), so it never
disturbs a running `npm run dev`. Every `/api` call and the event socket are stubbed (`e2e/fixtures.ts`): no
backend and no model keys are needed. `E2E_DEV=1 npm run test:e2e` reuses the dev server instead (faster to start,
but on-demand compiling can make the first request of a route slow). First run: `npx playwright install chromium`.

From the repository root, `make lint-ui` ratchets UI debt (`scripts/lint_ui_debt.py`) and checks token contrast
(`scripts/check_ui_contrast.py`); the ceilings live in `tasks/quality/ceilings.toml`.

## Architecture

The UI communicates with the Weebot backend via:

- **REST API** — session CRUD, model listing, dashboard data
- **WebSocket** — real-time event streaming per session
- **SSE** — server-sent events for live updates

## Source layout

```
src/
  types/        pure types: backend event mirror (events.ts), Remote<T>
  lib/          pure functions, no React: session-reducer, composer, scroll, announce, sessions, api
  hooks/        React bindings over lib/ and providers/
  providers/    process-wide services: EventStream, Toast, Theme, Shell (page slots), Announcer
  components/
    ui/         primitives (shadcn over base-ui); know nothing about Weebot
    common/     StateView (Remote<T>), StatusBadge, ConfirmDialog
    shell/      AppShell, AppBar, ConsoleShell, SessionRail, ResponsivePanel
    conversation/, dock/, ...   Weebot-specific composition
  app/          routes only. (console)/ is the route group whose layout mounts the rail and dock once
```

Dependencies point down only. ESLint enforces two rules: `components/ui` imports nothing from `hooks/`, `providers/`
or `lib/` except `lib/utils`, and `lib/` imports no React.

Conventions that the tests and the ratchets hold in place:

- One `<main>` per page (in `AppShell`); one `<h1>` per page (the app bar shows the page's title, or the page renders its own).
- Heights use `dvh`, never `vh`. Type is never below 12 px (`text-xs`). Status is never colour alone (`StatusBadge`).
- State variants in `components/ui` must be attributes base-ui really emits (`data-[orientation=horizontal]:`, not
  `data-horizontal:`); `primitives.contract.test.tsx` fails otherwise.
- Data that loads is a `Remote<T>` rendered by `StateView`; a modal is the `Dialog` primitive, never a hand-rolled overlay.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API base URL |

## Connecting to Backend

1. Start the Weebot API: `python -m weebot.interfaces.web.main`
2. Start the UI: `npm run dev`
3. Open [http://localhost:3000](http://localhost:3000)

For WebSocket features, the UI connects directly to the backend's WebSocket endpoint.
