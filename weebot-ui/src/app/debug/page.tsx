"use client";

import { useWebSocketDebug } from "@/hooks/useWebSocketDebug";
import { useEffect, useState } from "react";
import { notFound } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ENDPOINTS } from "@/lib/endpoints";

export default function DebugPage() {
  // Raw wire-protocol debugging tool — not meant for production operators.
  if (process.env.NODE_ENV === "production") {
    notFound();
  }

  // The default id embeds the clock, so it is made after mount (the server cannot match it) and
  // the console below, which connects on mount, only renders once there is an id.
  const [initialId, setInitialId] = useState<string | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- dev-only debug tool; reading the clock after mount is the point
    setInitialId("test-session-" + Date.now());
  }, []);

  return (
    <div className="container mx-auto max-w-4xl px-4 py-8 font-mono">
      <h2 className="mb-6 text-2xl font-bold">WebSocket Debug Page</h2>
      {initialId ? <DebugConsole initialId={initialId} /> : null}
    </div>
  );
}

function DebugConsole({ initialId }: { initialId: string }) {
  const [sessionId, setSessionId] = useState(initialId);
  const { isConnected, error, logs, connect, disconnect, send, clearLogs } = useWebSocketDebug(sessionId);

  return (
    <>
      <div className="mb-5 space-y-2">
        <Label htmlFor="debug-session-id">Session ID</Label>
        <Input
          id="debug-session-id"
          name="session-id"
          type="text"
          autoComplete="off"
          spellCheck={false}
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          className="max-w-sm"
        />
      </div>

      <div className="mb-5 flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={connect} disabled={isConnected}>
          Connect
        </Button>
        <Button variant="outline" size="sm" onClick={disconnect} disabled={!isConnected}>
          Disconnect
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => send(JSON.stringify({ type: "ping", time: Date.now() }))}
          disabled={!isConnected}
        >
          Send Ping
        </Button>
        <Button variant="outline" size="sm" onClick={clearLogs}>
          Clear Logs
        </Button>
      </div>

      <div className="mb-5">
        <strong>Status: </strong>
        <span className={isConnected ? "text-status-live-fg" : "text-status-error-fg"}>
          {isConnected ? "CONNECTED" : "DISCONNECTED"}
        </span>
        {error && <span className="ml-2 text-status-error-fg">Error: {error}</span>}
      </div>

      <div
        role="log"
        aria-label="WebSocket log"
        tabIndex={0}
        className="focus-ring h-[400px] overflow-y-auto overscroll-contain rounded-md border bg-surface-1 p-2.5 text-xs"
      >
        {logs.length === 0 && <div className="text-muted-foreground">No logs yet…</div>}
        {logs.map((log) => (
          <div key={log.id} className="mb-0.5 break-words">
            {log.text}
          </div>
        ))}
      </div>

      <div className="mt-5">
        <h2 className="mb-2 font-semibold">Troubleshooting:</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>Make sure backend is running: <code>python -m weebot.interfaces.web.main</code></li>
          <li>Check browser console for CORS errors</li>
          <li>Check Windows Firewall/antivirus isn&apos;t blocking port 8000</li>
          <li>Try opening <a href={`${ENDPOINTS.origin}/`} target="_blank" rel="noreferrer" className="underline">{ENDPOINTS.origin}/</a> in a new tab</li>
        </ul>
      </div>
    </>
  );
}
