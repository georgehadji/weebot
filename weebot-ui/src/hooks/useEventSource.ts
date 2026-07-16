"use client";

/**
 * HTTP polling fallback when WebSocket fails
 * Uses Server-Sent Events or simple polling
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentEvent } from "@/types/events";

interface EventSourceHook {
  isConnected: boolean;
  lastMessage: AgentEvent | null;
  error: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
const POLL_INTERVAL = 2000; // 2 seconds

export function useEventSource(sessionId?: string): EventSourceHook {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<AgentEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastEventIdRef = useRef<string | null>(null);

  const pollEvents = useCallback(async () => {
    if (!sessionId) return;

    try {
      const url = new URL(`${API_BASE}/sessions/${sessionId}/events`);
      if (lastEventIdRef.current) {
        url.searchParams.set("after", lastEventIdRef.current);
      }

      const response = await fetch(url.toString());
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const events: AgentEvent[] = await response.json();
      
      if (events.length > 0) {
        // Get the latest event
        const latest = events[events.length - 1];
        setLastMessage(latest);
        lastEventIdRef.current = latest.id || String(Date.now());
      }

      setIsConnected(true);
      setError(null);
    } catch (e) {
      setError(String(e));
      setIsConnected(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setIsConnected(false);
      return;
    }

    // Initial poll
    pollEvents();

    // Set up polling interval
    intervalRef.current = setInterval(pollEvents, POLL_INTERVAL);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [sessionId, pollEvents]);

  return { isConnected, lastMessage, error };
}
