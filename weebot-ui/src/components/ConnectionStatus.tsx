"use client";

import { FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useIntlContext } from "@/hooks/useIntlContext";
import { usePageVisible } from "@/hooks/usePageVisible";
import { useStoredValue } from "@/hooks/useStoredValue";
import { formatTime } from "@/lib/format";
import { apiBase, apiKey, setApiKey } from "@/lib/settings";
import { STORAGE_KEYS } from "@/lib/storage";
import { useToast } from "@/providers/ToastProvider";

const POLL_INTERVAL_MS = 10_000;

type ProbeResult = { status: "connected"; error: null } | { status: "error"; error: string };

// Reads the key from storage on every call. The previous version gated on
// `hasApiKey` state, which the 10s poll captured at mount, so after a key
// was saved the poll kept probing without it.
async function probeBackend(): Promise<ProbeResult> {
  const headers: Record<string, string> = {};
  const stored = apiKey();
  if (stored) headers["X-API-Key"] = stored;

  try {
    const response = await fetch(`${apiBase()}/health`, { headers });
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
  const [nextRetryAt, setNextRetryAt] = useState<number | null>(null);
  const [keyDraft, setKeyDraft] = useState("");
  const [keyError, setKeyError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const [storedKey] = useStoredValue("session", STORAGE_KEYS.apiKey);
  const hasApiKey = storedKey !== null;
  const visible = usePageVisible();
  const ctx = useIntlContext();
  const { toast } = useToast();
  const keyInputId = useId();
  const keyErrorId = useId();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const applyProbe = useCallback((result: ProbeResult) => {
    if (!mounted.current) return;
    setStatus(result.status);
    setError(result.error);
    setNextRetryAt(Date.now() + POLL_INTERVAL_MS);
  }, []);

  // `quiet` keeps the current panel on screen while probing (the key form shows its own busy
  // button); a plain retry swaps in the "Connecting…" panel.
  const checkConnection = useCallback(
    async (quiet = false) => {
      if (!quiet) {
        setStatus("checking");
        setError(null);
      }
      applyProbe(await probeBackend());
    },
    [applyProbe]
  );

  const save = useAsyncAction(async () => {
    const trimmed = keyDraft.trim();
    if (!trimmed) {
      setKeyError("Enter an API key to save.");
      return;
    }
    setKeyError(null);
    setApiKey(trimmed);
    setKeyDraft("");
    await checkConnection(true);
  });

  const handleSaveApiKey = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void save.run();
  };

  const removeApiKey = async () => {
    setApiKey(null);
    toast({ title: "API key removed", variant: "success" });
    await checkConnection(true);
  };

  // Background polls update in place; only a user-triggered retry shows the
  // "Connecting…" state, so the panel no longer flashes every 10s. A hidden tab does not poll,
  // and probes again as soon as it is visible.
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    const poll = async () => {
      const result = await probeBackend();
      if (!cancelled) applyProbe(result);
    };
    void poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [visible, applyProbe]);

  if (status === "checking") {
    return (
      <Alert>
        <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />
        <AlertTitle>Connecting…</AlertTitle>
        <AlertDescription>Checking backend connection</AlertDescription>
      </Alert>
    );
  }

  if (status === "connected") {
    return (
      <Alert className="border-status-live/40 bg-status-live/10">
        <CheckCircle2 className="h-4 w-4 text-status-live-fg" aria-hidden="true" />
        <AlertTitle className="text-status-live-fg">Connected</AlertTitle>
        <AlertDescription className="space-y-2">
          <p>Backend is running and accessible</p>
          {hasApiKey && (
            <div className="flex items-center gap-2 mt-1">
              <KeyRound className="h-3 w-3 text-status-live-fg" aria-hidden="true" />
              <span className="text-xs text-muted-foreground">API key configured</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setRemoving(true)}
                className="h-6 text-xs text-status-error-fg hover:text-status-error-fg/80"
              >
                Remove API Key
              </Button>
            </div>
          )}
          <ConfirmDialog
            open={removing}
            onOpenChange={setRemoving}
            title="Remove the API key?"
            description="This tab will stop sending the key. Requests the backend protects will fail until you enter it again."
            confirmLabel="Remove API Key"
            destructive
            onConfirm={removeApiKey}
          />
        </AlertDescription>
      </Alert>
    );
  }

  const retryTime = nextRetryAt === null ? null : formatTime(nextRetryAt, ctx);

  return (
    <Alert variant="destructive">
      <AlertCircle className="h-4 w-4" aria-hidden="true" />
      <AlertTitle>Connection Error</AlertTitle>
      <AlertDescription className="space-y-2">
        <p>{error}</p>
        <p className="text-sm">
          Make sure the backend is running:
        </p>
        <code translate="no" className="block bg-muted p-2 rounded text-xs">
          python -m weebot.interfaces.web.main
        </code>

        {/* API key input — shown on any connection error */}
        <form onSubmit={handleSaveApiKey} noValidate className="space-y-1.5 pt-2">
          <Label htmlFor={keyInputId}>API key</Label>
          <div className="flex gap-2 items-center">
            <Input
              id={keyInputId}
              name="api-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="Enter WEEBOT_API_KEY…"
              value={keyDraft}
              onChange={(e) => {
                setKeyDraft(e.target.value);
                setKeyError(null);
              }}
              aria-invalid={keyError ? true : undefined}
              aria-describedby={keyError ? keyErrorId : undefined}
              className="flex-1 text-sm"
            />
            <Button type="submit" variant="outline" size="sm" loading={save.pending}>
              Save Key
            </Button>
          </div>
          {keyError && (
            <p id={keyErrorId} role="alert" className="text-xs">
              {keyError}
            </p>
          )}
        </form>

        {hasApiKey && <p className="text-xs text-muted-foreground">API key saved.</p>}
        <p className="text-xs text-muted-foreground">
          {retryTime ? `Next automatic retry at ${retryTime}.` : "Retrying now."}
        </p>

        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void checkConnection()} className="mt-1">
            Retry Connection
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}
