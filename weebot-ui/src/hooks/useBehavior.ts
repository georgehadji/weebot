"use client";

/**
 * React hook for Weebot behavior tracking
 * Provides real-time event streaming and trust score monitoring
 */

import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

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

  const connect = useCallback(() => {
    const wsUrl = sessionId 
      ? `${WS_URL}/behavior/ws/session/${sessionId}`
      : `${WS_URL}/behavior/ws`;

    const ws = new WebSocket(wsUrl);
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

    ws.onerror = (e) => {
      console.error("[Behavior] WebSocket error:", e);
    };

    ws.onclose = () => {
      console.log("[Behavior] WebSocket disconnected");
      setIsConnected(false);
      wsRef.current = null;
      
      // Auto reconnect
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, 5000);
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

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

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
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export function useBehaviorREST(sessionId?: string) {
  const [trustScore, setTrustScore] = useState<TrustScore | null>(null);
  const [recentActions, setRecentActions] = useState<RecentAction[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const fetchTrust = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/behavior/trust`);
      if (res.ok) {
        const data = await res.json();
        setTrustScore(data);
      }
    } catch (e) {
      console.error("[Behavior] Failed to fetch trust:", e);
    }
  }, []);

  const fetchRecent = useCallback(async (count = 10) => {
    try {
      const url = new URL(`${API_URL}/behavior/recent`);
      url.searchParams.set("count", String(count));
      if (sessionId) {
        url.searchParams.set("session_id", sessionId);
      }
      
      const res = await fetch(url.toString());
      if (res.ok) {
        const data = await res.json();
        setRecentActions(data);
      }
    } catch (e) {
      console.error("[Behavior] Failed to fetch recent:", e);
    }
  }, [sessionId]);

  const markOverride = useCallback(async (timestamp: string, reason: string) => {
    try {
      const res = await fetch(`${API_URL}/behavior/override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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

  useEffect(() => {
    refreshAll();
    
    // Poll every 5 seconds as fallback
    const interval = setInterval(refreshAll, 5000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  return {
    trustScore,
    recentActions,
    isLoading,
    refreshAll,
    markOverride
  };
}
