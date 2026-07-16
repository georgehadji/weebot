"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentEvent } from "@/types/events";

interface WebSocketHook {
  isConnected: boolean;
  lastMessage: AgentEvent | null;
  sendMessage: (message: unknown) => boolean;
  error: string | null;
  reconnect: () => void;
}

// Backend WebSocket URL (must connect directly to backend)
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";

// Cache the WS token so we only fetch it once
let _cachedWsToken: string | null = null;
let _tokenFetchInFlight: Promise<string | null> | null = null;

async function _resolveWsToken(): Promise<string | null> {
  if (_cachedWsToken !== null) return _cachedWsToken;
  if (_tokenFetchInFlight) return _tokenFetchInFlight;

  _tokenFetchInFlight = (async () => {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) return null;
      const data = await res.json();
      // If backend returns a ws_token, use it
      _cachedWsToken = data.ws_token || null;
      return _cachedWsToken;
    } catch {
      return null;
    }
  })();

  return _tokenFetchInFlight;
}

// WebSocket ready states
const WS_READY_STATES = {
  CONNECTING: 0,
  OPEN: 1,
  CLOSING: 2,
  CLOSED: 3,
};

export function useWebSocket(sessionId?: string): WebSocketHook {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<AgentEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isManualCloseRef = useRef(false);

  const MAX_RECONNECT_ATTEMPTS = 5;
  const BASE_RECONNECT_DELAY = 1000; // 1 second

  const connect = useCallback(async () => {
    // Don't connect if already connected or connecting
    if (wsRef.current?.readyState === WS_READY_STATES.CONNECTING || 
        wsRef.current?.readyState === WS_READY_STATES.OPEN) {
      console.log("WebSocket already connected or connecting, skipping...");
      return;
    }

    try {
      // Resolve auth token (if backend requires one)
      const token = await _resolveWsToken();

      const wsUrl = sessionId
        ? `${WS_BASE}/sessions/${sessionId}${token ? `?token=${token}` : ""}`
        : `${WS_BASE}${token ? `?token=${token}` : ""}`;

      console.log(`Connecting to WebSocket: ${wsUrl.split("?")[0]}${token ? "?token=***" : ""}`);
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log("WebSocket connected successfully");
        setIsConnected(true);
        setError(null);
        reconnectAttemptsRef.current = 0;
        isManualCloseRef.current = false;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as AgentEvent;
          setLastMessage(data);
        } catch (e) {
          console.error("Failed to parse WebSocket message:", e);
        }
      };

      ws.onerror = (e) => {
        const errorMsg = "WebSocket error occurred";
        setError(errorMsg);
        console.error("WebSocket error:", e);
        console.error("WebSocket URL:", wsUrl);
        console.error("WebSocket readyState:", ws.readyState);
      };

      ws.onclose = (event) => {
        console.log(`WebSocket disconnected: code=${event.code}, reason=${event.reason}, wasClean=${event.wasClean}`);
        setIsConnected(false);
        
        // Don't reconnect if manually closed
        if (isManualCloseRef.current) {
          console.log("WebSocket was manually closed, not reconnecting");
          return;
        }

        // Attempt to reconnect with exponential backoff
        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          const delay = BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptsRef.current);
          reconnectAttemptsRef.current++;
          
          console.log(`Attempting to reconnect in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})...`);
          
          if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
          }
          
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          setError(`Failed to reconnect after ${MAX_RECONNECT_ATTEMPTS} attempts`);
          console.error(`Max reconnection attempts (${MAX_RECONNECT_ATTEMPTS}) reached`);
        }
      };

      wsRef.current = ws;
    } catch (e) {
      setError("Failed to connect to WebSocket");
      console.error("WebSocket connection error:", e);
    }
  }, [sessionId]);

  const reconnect = useCallback(() => {
    console.log("Manual reconnect requested");
    reconnectAttemptsRef.current = 0;
    isManualCloseRef.current = false;
    
    if (wsRef.current) {
      isManualCloseRef.current = true;
      wsRef.current.close();
      wsRef.current = null;
    }
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    
    // Small delay before reconnecting
    setTimeout(() => {
      connect();
    }, 100);
  }, [connect]);

  useEffect(() => {
    isManualCloseRef.current = false;
    reconnectAttemptsRef.current = 0;
    connect();

    return () => {
      isManualCloseRef.current = true;
      
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, sessionId]);

  const sendMessage = useCallback((message: unknown): boolean => {
    if (wsRef.current?.readyState === WS_READY_STATES.OPEN) {
      try {
        wsRef.current.send(JSON.stringify(message));
        return true;
      } catch (e) {
        console.error("Failed to send WebSocket message:", e);
        return false;
      }
    } else {
      console.warn("WebSocket is not connected, cannot send message");
      return false;
    }
  }, []);

  return { isConnected, lastMessage, sendMessage, error, reconnect };
}
