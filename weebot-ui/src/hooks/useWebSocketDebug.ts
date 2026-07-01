"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface WebSocketDebugHook {
  isConnected: boolean;
  error: string | null;
  logs: string[];
  connect: () => void;
  disconnect: () => void;
  send: (msg: string) => boolean;
  clearLogs: () => void;
}

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";

export function useWebSocketDebug(sessionId?: string): WebSocketDebugHook {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const logsRef = useRef<string[]>([]);

  const addLog = useCallback((msg: string) => {
    const time = new Date().toLocaleTimeString();
    const entry = `[${time}] ${msg}`;
    logsRef.current = [...logsRef.current.slice(-49), entry]; // Keep last 50
    setLogs(logsRef.current);
    console.log(entry);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      addLog("Already connected");
      return;
    }

    const url = sessionId ? `${WS_BASE}/sessions/${sessionId}` : WS_BASE;
    addLog(`Connecting to ${url}...`);

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        addLog(`✅ OPEN - readyState=${ws.readyState}`);
        setIsConnected(true);
        setError(null);
      };

      ws.onmessage = (e) => {
        addLog(`📥 MESSAGE: ${e.data.substring(0, 100)}`);
      };

      ws.onerror = (e) => {
        const evt = e as Event;
        addLog(`❌ ERROR - isTrusted=${evt.isTrusted}`);
        setError("WebSocket error occurred");
      };

      ws.onclose = (e) => {
        addLog(`🔒 CLOSE - code=${e.code}, reason="${e.reason}", clean=${e.wasClean}`);
        setIsConnected(false);
        wsRef.current = null;
      };
    } catch (e) {
      addLog(`💥 EXCEPTION: ${e}`);
      setError(String(e));
    }
  }, [sessionId, addLog]);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      addLog("Disconnecting...");
      wsRef.current.close(1000, "User disconnect");
      wsRef.current = null;
    }
  }, [addLog]);

  const send = useCallback((msg: string): boolean => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(msg);
      addLog(`📤 SENT: ${msg.substring(0, 100)}`);
      return true;
    }
    addLog("⚠️ Cannot send - not connected");
    return false;
  }, [addLog]);

  const clearLogs = useCallback(() => {
    logsRef.current = [];
    setLogs([]);
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { isConnected, error, logs, connect, disconnect, send, clearLogs };
}
