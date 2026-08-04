"use client";

/**
 * useSessionEvents — subscribe a component to one session's live events.
 *
 * Thin consumer of EventStreamProvider's connection pool: multiple
 * components watching the same sessionId share one underlying
 * WebSocket/SSE connection instead of each opening their own (which is
 * what the old per-component `useWebSocket` did).
 */

import { useEffect, useState } from "react";
import { AgentEvent } from "@/types/events";
import { useEventStreamContext } from "@/providers/EventStreamProvider";

interface SessionEventsHook {
  isConnected: boolean;
  lastMessage: AgentEvent | null;
}

export function useSessionEvents(sessionId?: string): SessionEventsHook {
  const { subscribeSession, getSessionMode } = useEventStreamContext();
  const [lastMessage, setLastMessage] = useState<AgentEvent | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    const unsubscribe = subscribeSession(sessionId, (event) => {
      setLastMessage(event);
      setIsConnected(true);
    });

    // Poll the provider's connection mode so isConnected reflects
    // reconnect/fallback transitions the listener callback alone can't see.
    const interval = setInterval(() => {
      const mode = getSessionMode(sessionId);
      setIsConnected(mode === "websocket" || mode === "sse");
    }, 1000);

    return () => {
      unsubscribe();
      clearInterval(interval);
    };
  }, [sessionId, subscribeSession, getSessionMode]);

  return { isConnected, lastMessage };
}
