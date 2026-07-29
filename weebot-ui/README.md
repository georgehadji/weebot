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
| `npm run lint` | Run ESLint |

## Architecture

The UI communicates with the Weebot backend via:

- **REST API** — session CRUD, model listing, dashboard data
- **WebSocket** — real-time event streaming per session
- **SSE** — server-sent events for live updates

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API base URL |

## Connecting to Backend

1. Start the Weebot API: `python -m weebot.interfaces.web.main`
2. Start the UI: `npm run dev`
3. Open [http://localhost:3000](http://localhost:3000)

For WebSocket features, the UI connects directly to the backend's WebSocket endpoint.
