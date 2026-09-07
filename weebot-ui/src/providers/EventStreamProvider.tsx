"use client";

/**
 * EventStreamProvider — Facade over the live event transport.
 *
 * Backend reality (see mission_center_ui_implementation_plan.md T0.4):
 * a session's AgentEvents are routed ONLY to /ws/sessions/{id} — never to
 * the global /ws socket (session isolation, verified by
 * test_event_broadcaster_wiring.py). So "one shared connection" here means
 * "one WebSocket per session_id, reused across every component watching
 * that session" (reference-counted), NOT "one socket for the whole app" —
 * that would require the backend to broadcast every session's traffic
 * globally, which the isolation guarantee deliberately rules out.
 *
 * SessionPresenceEvent is the one event type that IS global (no session_id
 * set — see its docstring), delivered over a single always-on connection
 * to /ws, independent of which session views are open.
 *
 * Strategy: WebSocket first; after repeated reconnect failures a session
 * connection falls back to polling /api/events/stream (SSE) and filters
 * client-side by session_id — that endpoint is a real, working, all-events
 * stream (unlike the old useEventSource.ts, which polled a REST endpoint
 * the backend never implemented).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AgentEvent, SessionPresenceEvent } from "@/types/events";

type Listener = (event: AgentEvent) => void;
type ConnectionMode = "connecting" | "websocket" | "sse" | "closed";

interface SessionConnection {
  listeners: Set<Listener>;
  ws: WebSocket | null;
  sseController: AbortController | null;
  mode: ConnectionMode;
  reconnectAttempts: number;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
}

interface EventStreamContextValue {
  subscribeSession: (sessionId: string, listener: Listener) => () => void;
  subscribePresence: (listener: (event: SessionPresenceEvent) => void) => () => void;
  getSessionMode: (sessionId: string) => ConnectionMode;
}

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 1000;

const EventStreamContext = createContext<EventStreamContextValue | null>(null);

function getWsToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem("weebot_api_key");
  } catch {
    return null;
  }
}

function getStreamUrls(): { ws: string; api: string } {
  const defaultWs = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";
  const defaultApi = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
  if (typeof window === "undefined") return { ws: defaultWs, api: defaultApi };
  try {
    const configuredWs = localStorage.getItem("weebot_ws_url")?.trim();
    const configuredBackend = localStorage.getItem("weebot_backend_url")?.trim();
    return {
      ws: configuredWs || defaultWs,
      api: configuredBackend ? `${configuredBackend.replace(/\/$/, "")}/api` : defaultApi,
    };
  } catch {
    return { ws: defaultWs, api: defaultApi };
  }
}

export function EventStreamProvider({ children }: { children: React.ReactNode }) {
  const sessionConnections = useRef<Map<string, SessionConnection>>(new Map());
  const presenceListeners = useRef<Set<(event: SessionPresenceEvent) => void>>(new Set());
  const presenceWsRef = useRef<WebSocket | null>(null);
  const presenceReconnectRef = useRef(0);
  const presenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [, forceRender] = useState(0);

  // ── per-session connections ──────────────────────────────────────

  const closeSessionConnection = useCallback((sessionId: string, conn: SessionConnection) => {
    if (conn.reconnectTimer) clearTimeout(conn.reconnectTimer);
    conn.ws?.close();
    conn.sseController?.abort();
    conn.ws = null;
    conn.sseController = null;
    conn.mode = "closed";
    sessionConnections.current.delete(sessionId);
  }, []);

  const startSessionSSE = useCallback((sessionId: string, conn: SessionConnection) => {
    const controller = new AbortController();
    conn.sseController = controller;
    conn.mode = "sse";
    forceRender((n) => n + 1);

    (async () => {
      try {
        const token = getWsToken();
        const headers: Record<string, string> = {};
        if (token) headers["X-API-Key"] = token;
        const response = await fetch(`${getStreamUrls().api}/events/stream`, {
          headers,
          signal: controller.signal,
        });
        if (!response.body) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() ?? "";
          for (const chunk of lines) {
            const dataLine = chunk.split("\n").find((l) => l.startsWith("data:"));
            if (!dataLine) continue;
            try {
              const event = JSON.parse(dataLine.slice(5).trim()) as AgentEvent;
              if (event.session_id === sessionId) {
                conn.listeners.forEach((l) => l(event));
              }
            } catch {
              // ignore malformed frame
            }
          }
        }
      } catch {
        // aborted or network error — connection just stays closed;
        // the consumer's next subscribe() call will retry from WS.
      }
    })();
  }, []);

  const connectSessionWs = useCallback(
    (sessionId: string, conn: SessionConnection) => {
      conn.mode = "connecting";
      const token = getWsToken();
      const url = `${getStreamUrls().ws}/sessions/${sessionId}${token ? `?token=${token}` : ""}`;
      const ws = new WebSocket(url);
      conn.ws = ws;

      ws.onopen = () => {
        conn.reconnectAttempts = 0;
        conn.mode = "websocket";
        forceRender((n) => n + 1);
      };

      ws.onmessage = (evt) => {
        try {
          const event = JSON.parse(evt.data) as AgentEvent;
          conn.listeners.forEach((l) => l(event));
        } catch {
          // ignore malformed frame
        }
      };

      ws.onclose = () => {
        if (conn.listeners.size === 0) return; // intentionally torn down
        if (conn.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          conn.reconnectAttempts += 1;
          const delay = BASE_RECONNECT_DELAY_MS * 2 ** (conn.reconnectAttempts - 1);
          conn.reconnectTimer = setTimeout(() => connectSessionWs(sessionId, conn), delay);
        } else {
          startSessionSSE(sessionId, conn);
        }
      };

      ws.onerror = () => {
        // onclose fires next and drives reconnect/fallback — nothing to do here.
      };
    },
    [startSessionSSE]
  );

  const subscribeSession = useCallback(
    (sessionId: string, listener: Listener) => {
      let conn = sessionConnections.current.get(sessionId);
      if (!conn) {
        conn = {
          listeners: new Set(),
          ws: null,
          sseController: null,
          mode: "connecting",
          reconnectAttempts: 0,
          reconnectTimer: null,
        };
        sessionConnections.current.set(sessionId, conn);
        connectSessionWs(sessionId, conn);
      }
      conn.listeners.add(listener);

      return () => {
        const current = sessionConnections.current.get(sessionId);
        if (!current) return;
        current.listeners.delete(listener);
        if (current.listeners.size === 0) {
          closeSessionConnection(sessionId, current);
        }
      };
    },
    [connectSessionWs, closeSessionConnection]
  );

  const getSessionMode = useCallback((sessionId: string): ConnectionMode => {
    return sessionConnections.current.get(sessionId)?.mode ?? "closed";
  }, []);

  // ── global presence connection ───────────────────────────────────

  const connectPresence = useCallback(() => {
    const token = getWsToken();
    const url = `${getStreamUrls().ws}${token ? `?token=${token}` : ""}`;
    const ws = new WebSocket(url);
    presenceWsRef.current = ws;

    ws.onopen = () => {
      presenceReconnectRef.current = 0;
    };
    ws.onmessage = (evt) => {
      try {
        const event = JSON.parse(evt.data) as AgentEvent;
        if (event.type === "session_presence") {
          presenceListeners.current.forEach((l) => l(event as SessionPresenceEvent));
        }
      } catch {
        // ignore malformed frame
      }
    };
    ws.onclose = () => {
      if (presenceListeners.current.size === 0) return;
      if (presenceReconnectRef.current < MAX_RECONNECT_ATTEMPTS) {
        const attempt = presenceReconnectRef.current;
        presenceReconnectRef.current += 1;
        const delay = BASE_RECONNECT_DELAY_MS * 2 ** attempt;
        presenceTimerRef.current = setTimeout(connectPresence, delay);
      }
    };
  }, []);

  const subscribePresence = useCallback(
    (listener: (event: SessionPresenceEvent) => void) => {
      if (presenceListeners.current.size === 0 && !presenceWsRef.current) {
        connectPresence();
      }
      presenceListeners.current.add(listener);
      return () => {
        presenceListeners.current.delete(listener);
        if (presenceListeners.current.size === 0) {
          if (presenceTimerRef.current) clearTimeout(presenceTimerRef.current);
          presenceWsRef.current?.close();
          presenceWsRef.current = null;
        }
      };
    },
    [connectPresence]
  );

  useEffect(() => {
    const connections = sessionConnections.current;
    return () => {
      connections.forEach((conn, id) => closeSessionConnection(id, conn));
      presenceWsRef.current?.close();
    };
  }, [closeSessionConnection]);

  const value = useMemo<EventStreamContextValue>(
    () => ({ subscribeSession, subscribePresence, getSessionMode }),
    [subscribeSession, subscribePresence, getSessionMode]
  );

  return <EventStreamContext.Provider value={value}>{children}</EventStreamContext.Provider>;
}

export function useEventStreamContext(): EventStreamContextValue {
  const ctx = useContext(EventStreamContext);
  if (!ctx) throw new Error("useEventStreamContext must be used within EventStreamProvider");
  return ctx;
}
