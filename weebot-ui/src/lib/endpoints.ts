// The backend URLs, in one place. NEXT_PUBLIC_* values are read by their
// literal names because Next.js inlines only those into the browser bundle.

const DEFAULT_API = "http://localhost:8000/api";
const DEFAULT_WS = "ws://localhost:8000/ws";

export interface Endpoints {
  /** REST base, ending in /api. */
  api: string;
  /** The app's event socket, ending in /ws. */
  ws: string;
  /** The behavior-tracker socket the backend mounts at /api/behavior/ws. */
  behaviorWs: string;
  /** Backend origin, for links to the server itself. */
  origin: string;
}

export function endpointsFrom(apiUrl?: string, wsUrl?: string): Endpoints {
  const api = (apiUrl || DEFAULT_API).replace(/\/$/, "");
  const ws = (wsUrl || DEFAULT_WS).replace(/\/$/, "");
  const wsOrigin = ws.replace(/\/ws$/, "");
  return {
    api,
    ws,
    behaviorWs: `${wsOrigin}/api/behavior/ws`,
    origin: api.replace(/\/api$/, ""),
  };
}

export const ENDPOINTS: Endpoints = endpointsFrom(
  process.env.NEXT_PUBLIC_API_URL,
  process.env.NEXT_PUBLIC_WS_URL,
);
