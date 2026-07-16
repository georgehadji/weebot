"use client";

/**
 * Unified event hook - tries WebSocket first, falls back to HTTP polling
 */

import { useEffect, useState } from "react";
import { AgentEvent } from "@/types/events";
import { useWebSocket } from "./useWebSocket";
import { useEventSource } from "./useEventSource";

interface EventsHook {
  isConnected: boolean;
  lastMessage: AgentEvent | null;
  error: string | null;
  sendMessage: (message: unknown) => boolean;
  connectionMode: "websocket" | "polling" | "none";
}

export function useEvents(sessionId?: string): EventsHook {
  const [connectionMode, setConnectionMode] = useState<"websocket" | "polling" | "none">("none");

  // Try WebSocket first
  const ws = useWebSocket(sessionId);

  // Fallback to HTTP polling
  const poll = useEventSource(sessionId);

  // Determine which mode to use
  useEffect(() => {
    if (ws.isConnected) {
      setConnectionMode("websocket");
    } else if (poll.isConnected) {
      setConnectionMode("polling");
    } else {
      setConnectionMode("none");
    }
  }, [ws.isConnected, poll.isConnected]);

  // Use WebSocket if connected, otherwise polling
  const isConnected = ws.isConnected || poll.isConnected;
  const lastMessage = ws.lastMessage || poll.lastMessage;
  const error = ws.error && !poll.isConnected ? ws.error : poll.error;

  return {
    isConnected,
    lastMessage,
    error,
    sendMessage: ws.sendMessage,
    connectionMode,
  };
}
