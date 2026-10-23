"use client";

/**
 * React hook for Weebot behavior tracking
 * Provides real-time event streaming and trust score monitoring
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ENDPOINTS } from "@/lib/endpoints";
import { authHeaders, getApiBase, withToken } from "@/lib/api";


export interface BehaviorEvent {
  type: "file.created" | "file.modified" | "file.deleted" | "file.moved";
  timestamp: string;
  path: string;
  session_id: string;
  agent_version: string;
}

export interface TrustScore {
  score_percentage: number;
  score: number;
  total_actions: number;
  overrides: number;
  last_updated: string;
  status: "trusted" | "review" | "supervision";
}

interface UseBehaviorReturn {
  events: BehaviorEvent[];
  trustScore: TrustScore | null;
  isConnected: boolean;
  recentActions: RecentAction[];
  sendPing: () => void;
  refreshTrust: () => void;
}

interface UseBehaviorRestReturn {
  trustScore: TrustScore | null;
  recentActions: RecentAction[];
  isLoading: boolean;
  isUnavailable: boolean;
  refreshAll: () => Promise<void>;
  markOverride: (timestamp: string, reason: string) => Promise<boolean>;
}

export interface RecentAction {
  timestamp: string;
  action: string;
  path: string;
  is_override: boolean;
}

export function useBehavior(sessionId?: string): UseBehaviorReturn {
  const [events, setEvents] = useState<BehaviorEvent[]>([]);
  const [trustScore, setTrustScore] = useState<TrustScore | null>(null);
  const [recentActions, setRecentActions] = useState<RecentAction[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    // Set by cleanup. Closing the socket on unmount fires onclose, which
    // used to schedule a reconnect for a component that no longer existed.
    let disposed = false;

    function connect() {
      const wsUrl = sessionId
        ? `${ENDPOINTS.behaviorWs}/session/${sessionId}`
        : ENDPOINTS.behaviorWs;

      const ws = new WebSocket(withToken(wsUrl));
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("[Behavior] WebSocket connected");
        setIsConnected(true);
        
        // Request recent actions
        ws.send(JSON.stringify({ action: "get_recent", count: 20 }));
      };

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          
          switch (data.type) {
            case "file.created":
            case "file.modified":
            case "file.deleted":
            case "file.moved":
              setEvents((prev) => [data, ...prev].slice(0, 100));
              break;
              
            case "trust.update":
              setTrustScore({
                score_percentage: data.score_percentage || data.score,
                score: data.score,
                total_actions: data.total_actions,
                overrides: data.overrides,
                last_updated: data.last_updated,
                status: data.status
              });
              break;
              
            case "recent.actions":
              setRecentActions(data.actions || []);
              break;
              
            case "connected":
              console.log("[Behavior] Server confirmed connection");
              break;
              
            case "keepalive":
              // Just a keepalive, ignore
              break;
          }
        } catch (err) {
          console.error("[Behavior] Failed to parse message:", err);
        }
      };

      ws.onerror = () => {
        // Browsers deliberately expose no useful detail for WebSocket errors.
        // `onclose` below moves the panel into its REST polling fallback and
        // retries in the background, so logging an opaque `{}` only creates
        // a false-alarm developer overlay for the operator.
        setIsConnected(false);
      };

      ws.onclose = () => {
        console.log("[Behavior] WebSocket disconnected");
        setIsConnected(false);
        wsRef.current = null;

        // Auto reconnect
        if (disposed) return;
        reconnectTimeoutRef.current = setTimeout(connect, 5000);
      };
    }

    connect();

    return () => {
      disposed = true;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [sessionId]);

  const sendPing = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "ping" }));
    }
  }, []);

  const refreshTrust = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "get_trust" }));
    }
  }, []);

  return {
    events,
    trustScore,
    isConnected,
    recentActions,
    sendPing,
    refreshTrust
  };
}

// Hook for REST API fallback
export function useBehaviorREST(sessionId?: string) {
  const [trustScore, setTrustScore] = useState<TrustScore | null>(null);
  const [recentActions, setRecentActions] = useState<RecentAction[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUnavailable, setIsUnavailable] = useState(false);

  const fetchTrust = useCallback(async () => {
    try {
      const res = await fetch(`${getApiBase()}/behavior/trust`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setTrustScore(data);
        setIsUnavailable(false);
      } else {
        setIsUnavailable(true);
      }
    } catch {
      // This is the expected fallback path while the local backend is
      // starting, stopped, or unreachable. Surface it as UI state rather
      // than repeatedly triggering the development error overlay.
      setIsUnavailable(true);
    }
  }, []);

  const fetchRecent = useCallback(async (count = 10) => {
    try {
      const params = new URLSearchParams({ count: String(count) });
      if (sessionId) {
        params.set("session_id", sessionId);
      }
      
      const res = await fetch(`${getApiBase()}/behavior/recent?${params}`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setRecentActions(data);
        setIsUnavailable(false);
      } else {
        setIsUnavailable(true);
      }
    } catch {
      setIsUnavailable(true);
    }
  }, [sessionId]);

  const markOverride = useCallback(async (timestamp: string, reason: string) => {
    try {
      const res = await fetch(`${getApiBase()}/behavior/override`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ timestamp, reason })
      });
      return res.ok;
    } catch (e) {
      console.error("[Behavior] Failed to mark override:", e);
      return false;
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setIsLoading(true);
    await Promise.all([fetchTrust(), fetchRecent(20)]);
    setIsLoading(false);
  }, [fetchTrust, fetchRecent]);

  // Background polls leave isLoading alone after the first one, so the panel
  // doesn't flip to "Loading..." every 5s; refreshAll (the manual button)
  // still shows it.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      await Promise.all([fetchTrust(), fetchRecent(20)]);
      if (!cancelled) setIsLoading(false);
    };
    poll();

    // Poll every 5 seconds as fallback
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [fetchTrust, fetchRecent]);

  return {
    trustScore,
    recentActions,
    isLoading,
    isUnavailable,
    refreshAll,
    markOverride
  } satisfies UseBehaviorRestReturn;
}
