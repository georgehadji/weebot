"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const POLL_INTERVAL_MS = 10_000;

type ProbeResult = { status: "connected"; error: null } | { status: "error"; error: string };

function healthUrl(): string {
  if (typeof window === "undefined") return "/api/health";
  const configured = localStorage.getItem("weebot_backend_url")?.trim();
  return configured ? `${configured.replace(/\/$/, "")}/api/health` : "/api/health";
}

// Reads the key from storage on every call. The previous version gated on
// `hasApiKey` state, which the 10s poll captured at mount, so after a key
// was saved the poll kept probing without it.
async function probeBackend(): Promise<ProbeResult> {
  const headers: Record<string, string> = {};
  try {
    const stored = sessionStorage.getItem("weebot_api_key");
    if (stored) headers["X-API-Key"] = stored;
  } catch { /* ignore */ }

  try {
    const response = await fetch(healthUrl(), { headers });
    if (response.ok) return { status: "connected", error: null };
    if (response.status === 401) {
      return { status: "error", error: "API key required — set WEEBOT_API_KEY on backend" };
    }
    const data = await response.json().catch(() => ({}));
    return { status: "error", error: data.error || `HTTP ${response.status}` };
  } catch {
    return { status: "error", error: "Cannot connect to backend" };
  }
}

export function ConnectionStatus() {
  const [status, setStatus] = useState<"checking" | "connected" | "error">("checking");
  const [error, setError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState<string>("");
  const [hasApiKey, setHasApiKey] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return !!sessionStorage.getItem("weebot_api_key");
    } catch {
      return false;
    }
  });

  const applyProbe = (result: ProbeResult) => {
    setStatus(result.status);
    setError(result.error);
  };

  const checkConnection = async () => {
    setStatus("checking");
    setError(null);
    applyProbe(await probeBackend());
  };

  const handleSaveApiKey = () => {
    const trimmed = apiKey.trim();
    if (trimmed) {
      try {
        sessionStorage.setItem("weebot_api_key", trimmed);
      } catch { /* ignore */ }
      setHasApiKey(true);
      setApiKey("");
      checkConnection();
    }
  };

  const handleClearApiKey = () => {
    try {
      sessionStorage.removeItem("weebot_api_key");
    } catch { /* ignore */ }
    setHasApiKey(false);
    checkConnection();
  };

  // Background polls update in place; only a user-triggered retry shows the
  // "Connecting..." state, so the panel no longer flashes every 10s.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const result = await probeBackend();
      if (cancelled) return;
      setStatus(result.status);
      setError(result.error);
    };
    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (status === "checking") {
    return (
      <Alert>
        <Loader2 className="h-4 w-4 animate-spin" />
        <AlertTitle>Connecting...</AlertTitle>
        <AlertDescription>Checking backend connection</AlertDescription>
      </Alert>
    );
  }

  if (status === "connected") {
    return (
      <Alert className="bg-green-50 border-green-200">
        <CheckCircle2 className="h-4 w-4 text-green-600" />
        <AlertTitle className="text-green-800">Connected</AlertTitle>
        <AlertDescription className="text-green-700 space-y-2">
          <p>Backend is running and accessible</p>
          {hasApiKey && (
            <div className="flex items-center gap-2 mt-1">
              <KeyRound className="h-3 w-3 text-green-500" />
              <span className="text-xs text-green-600">API key configured</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleClearApiKey}
                className="h-6 text-xs text-red-500 hover:text-red-700"
              >
                Clear
              </Button>
            </div>
          )}
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <Alert variant="destructive">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>Connection Error</AlertTitle>
      <AlertDescription className="space-y-2">
        <p>{error}</p>
        <p className="text-sm">
          Make sure the backend is running:
        </p>
        <code className="block bg-red-950 p-2 rounded text-xs">
          python -m weebot.interfaces.web.main
        </code>

        {/* API key input — shown on any connection error */}
        <div className="flex gap-2 items-center pt-2">
          <Input
            type="password"
            placeholder="Enter WEEBOT_API_KEY..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSaveApiKey(); }}
            className="flex-1 text-sm"
          />
          <Button variant="outline" size="sm" onClick={handleSaveApiKey}>
            Save Key
          </Button>
        </div>

        {hasApiKey && (
          <p className="text-xs text-muted-foreground">
            API key saved. Retrying connection...
          </p>
        )}

        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={checkConnection} className="mt-1">
            Retry Connection
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}
