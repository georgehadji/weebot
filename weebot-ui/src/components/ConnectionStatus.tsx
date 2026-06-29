"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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

  const checkConnection = async () => {
    setStatus("checking");
    setError(null);

    const headers: Record<string, string> = {};
    if (hasApiKey) {
      try {
        const stored = sessionStorage.getItem("weebot_api_key");
        if (stored) headers["X-API-Key"] = stored;
      } catch { /* ignore */ }
    }
    
    try {
      const response = await fetch("/api/health", { headers });
      if (response.ok) {
        setStatus("connected");
      } else if (response.status === 401) {
        setError("API key required — set WEEBOT_API_KEY on backend");
        setStatus("error");
      } else {
        const data = await response.json().catch(() => ({}));
        setError(data.error || `HTTP ${response.status}`);
        setStatus("error");
      }
    } catch {
      setError("Cannot connect to backend");
      setStatus("error");
    }
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

  useEffect(() => {
    checkConnection();
    // Check every 10 seconds
    const interval = setInterval(checkConnection, 10000);
    return () => clearInterval(interval);
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
