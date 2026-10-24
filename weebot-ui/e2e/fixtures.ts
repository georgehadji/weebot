/**
 * Deterministic backend for the browser tests: every `/api/**` call is answered from here and
 * the event socket is accepted and left silent, so the suite needs no server and no model keys.
 * Payload shapes mirror the backend's `SessionResponse` (types/events.ts).
 */
import type { Page, Route, WebSocketRoute } from "@playwright/test";

export interface FakeSession {
  id: string;
  user_id: string;
  agent_id: string;
  status: "pending" | "running" | "waiting" | "completed" | "failed";
  title: string | null;
  context: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  event_count: number;
}

const PROMPTS: [string, FakeSession["status"]][] = [
  ["tidy up my Downloads folder", "completed"],
  ["Summarise the Q3 report and list the three biggest risks", "running"],
  ["Weather at Γιαννιτσά tomorrow?", "completed"],
  ["Refactor the billing module to use the new tax API", "waiting"],
  ["Draft a release note for v2.4", "completed"],
  ["Find duplicate invoices in the March export", "failed"],
  ["Plan a three day trip to Thessaloniki", "completed"],
  ["Translate the onboarding guide to Greek", "pending"],
  ["Audit open ports on the staging host", "completed"],
];

export function makeSessions(count = PROMPTS.length): FakeSession[] {
  return Array.from({ length: count }, (_, i) => {
    const [prompt, status] = PROMPTS[i % PROMPTS.length];
    return {
      id: `sess-${i + 1}`,
      user_id: "anonymous",
      agent_id: "weebot-web",
      status,
      title: prompt,
      context: { last_prompt: prompt, model: "auto" },
      created_at: "2026-10-20T09:00:00Z",
      updated_at: "2026-10-20T09:05:00Z",
      event_count: 4 + i,
    };
  });
}

export function makeEvents(count: number): Record<string, unknown>[] {
  const events: Record<string, unknown>[] = [
    { type: "message", id: "e-0", role: "user", message: "Run the weekly report", timestamp: "2026-10-20T09:00:00Z" },
  ];
  for (let i = 1; i < count; i++) {
    events.push({
      type: "message",
      id: `e-${i}`,
      role: "assistant",
      message: `Step ${i}: working through the data set.`,
      timestamp: "2026-10-20T09:00:00Z",
    });
  }
  return events;
}

export interface BackendOptions {
  sessions?: FakeSession[];
  events?: Record<string, unknown>[];
  /** Make `GET /api/sessions` fail with this status. */
  failSessionList?: number;
  /** Make `POST /api/sessions/:id/input` fail with this status (read per request, so a test can clear it). */
  failInput?: number;
  /** Called with every event-socket the page opens, so a test can push live events. */
  onSocket?: (ws: WebSocketRoute) => void;
  /** Hold `POST /api/sessions/:id/input` this long before answering. */
  inputDelayMs?: number;
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export async function mockBackend(page: Page, options: BackendOptions = {}): Promise<void> {
  const sessions = options.sessions ?? makeSessions();
  const events = options.events ?? makeEvents(6);

  await page.routeWebSocket(/\/ws/, (ws) => options.onSocket?.(ws));

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = route.request().method();

    if (path === "/sessions" && method === "GET") {
      if (options.failSessionList) return json(route, { detail: "boom" }, options.failSessionList);
      return json(route, { sessions, total: sessions.length });
    }
    if (path === "/sessions/active") return json(route, { ok: true, data: [] });
    const input = path.match(/^\/sessions\/([^/]+)\/input$/);
    if (input && method === "POST") {
      if (options.inputDelayMs) await new Promise((r) => setTimeout(r, options.inputDelayMs));
      if (options.failInput) return json(route, { detail: "send failed" }, options.failInput);
      return json(route, { verb: "chat", session: sessions[0] });
    }
    const eventsMatch = path.match(/^\/sessions\/([^/]+)\/events$/);
    if (eventsMatch) return json(route, events);
    const one = path.match(/^\/sessions\/([^/]+)$/);
    if (one && method === "GET") {
      return json(route, sessions.find((s) => s.id === one[1]) ?? sessions[0]);
    }
    if (path === "/models" || path === "/models/available") return json(route, []);
    if (path === "/costs/summary") {
      return json(route, {
        ok: true,
        data: { total_decisions: 0, total_cost_usd: 0, avg_latency_ms: 0, cascade_hit_rate: 0, tiers: {} },
      });
    }
    if (path === "/behavior/trust") {
      return json(route, {
        score_percentage: 92, score: 0.92, total_actions: 40, overrides: 3,
        last_updated: "2026-10-20T09:05:00Z", status: "trusted",
      });
    }
    if (path.startsWith("/behavior/recent")) return json(route, []);
    if (path.startsWith("/health")) return json(route, { status: "ok", components: [], ready: true, alive: true });
    return json(route, {});
  });
}
