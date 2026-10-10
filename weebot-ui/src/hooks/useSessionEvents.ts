"use client";

/**
 * useSessionEvents — subscribe a component to one session's live events.
 *
 * Thin consumer of EventStreamProvider's connection pool: multiple
 * components watching the same sessionId share one underlying
 * WebSocket/SSE connection instead of each opening their own (which is
 * what the old per-component `useWebSocket` did).
 *
 * Events are delivered through `onEvent`, once per event. This used to
 * expose only `lastMessage` state, which dropped events: two frames that
 * arrived before React rendered were batched into one update, and the
 * consumer's effect only ever saw the second.
 */

import { useEffect, useEffectEvent, useState } from "react";
import { AgentEvent } from "@/types/events";
import { useEventStreamContext } from "@/providers/EventStreamProvider";

interface SessionEventsHook {
  isConnected: boolean;
}

export function useSessionEvents(
  sessionId?: string,
  onEvent?: (event: AgentEvent) => void
): SessionEventsHook {
  const { subscribeSession, getSessionMode } = useEventStreamContext();
  const [isConnected, setIsConnected] = useState(false);

  const handleEvent = useEffectEvent((event: AgentEvent) => {
    onEvent?.(event);
  });

  useEffect(() => {
    if (!sessionId) return;
    const unsubscribe = subscribeSession(sessionId, (event) => {
      handleEvent(event);
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

  return { isConnected };
}
