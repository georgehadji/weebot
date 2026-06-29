"use client";

import { useWebSocketDebug } from "@/hooks/useWebSocketDebug";
import { useState } from "react";

export default function DebugPage() {
  const [sessionId, setSessionId] = useState("test-session-" + Date.now());
  const { isConnected, error, logs, connect, disconnect, send, clearLogs } = useWebSocketDebug(sessionId);

  return (
    <div style={{ padding: 20, fontFamily: "monospace" }}>
      <h1>🔌 WebSocket Debug Page</h1>
      
      <div style={{ marginBottom: 20 }}>
        <label>Session ID: </label>
        <input
          type="text"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          style={{ width: 300, padding: 5 }}
        />
      </div>

      <div style={{ marginBottom: 20 }}>
        <button onClick={connect} disabled={isConnected}>Connect</button>
        <button onClick={disconnect} disabled={!isConnected}>Disconnect</button>
        <button onClick={() => send(JSON.stringify({ type: "ping", time: Date.now() }))} disabled={!isConnected}>
          Send Ping
        </button>
        <button onClick={clearLogs}>Clear Logs</button>
      </div>

      <div style={{ marginBottom: 20 }}>
        <strong>Status: </strong>
        <span style={{ color: isConnected ? "green" : "red" }}>
          {isConnected ? "CONNECTED" : "DISCONNECTED"}
        </span>
        {error && <span style={{ color: "red", marginLeft: 10 }}>Error: {error}</span>}
      </div>

      <div
        style={{
          border: "1px solid #333",
          padding: 10,
          height: 400,
          overflowY: "auto",
          background: "#1a1a1a",
          color: "#0f0",
          fontSize: 12,
        }}
      >
        {logs.length === 0 && <div style={{ color: "#666" }}>No logs yet...</div>}
        {logs.map((log, i) => (
          <div key={i} style={{ marginBottom: 2 }}>
            {log}
          </div>
        ))}
      </div>

      <div style={{ marginTop: 20 }}>
        <h3>Troubleshooting:</h3>
        <ul>
          <li>Make sure backend is running: <code>python -m weebot.interfaces.web.main</code></li>
          <li>Check browser console for CORS errors</li>
          <li>Check Windows Firewall/antivirus isn&apos;t blocking port 8000</li>
          <li>Try opening <a href="http://localhost:8000/" target="_blank" rel="noreferrer">http://localhost:8000/</a> in a new tab</li>
        </ul>
      </div>
    </div>
  );
}
