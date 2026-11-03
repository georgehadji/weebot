"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { CheckCircle2, ChevronRight } from "lucide-react";
import { ENDPOINTS } from "@/lib/endpoints";
import { setConnection } from "@/lib/settings";
import { STORAGE_KEYS } from "@/lib/storage";
import { useStoredValue } from "@/hooks/useStoredValue";
import { useAnnounce } from "@/providers/AnnouncerProvider";

/** An error message, or null when `value` is blank (allowed) or a URL with one of `protocols`. */
function urlError(value: string, protocols: string[], example: string): string | null {
  const text = value.trim();
  if (!text) return null;
  try {
    if (protocols.includes(new URL(text).protocol)) return null;
  } catch {
    // falls through to the message
  }
  return `Enter a full URL such as ${example}, or leave it blank.`;
}

export default function SettingsPage() {
  // Storage is read as an external store, so the first render matches the server (the defaults)
  // and the saved values appear right after hydration.
  const [storedBackend] = useStoredValue("local", STORAGE_KEYS.backendUrl);
  const [storedWs] = useStoredValue("local", STORAGE_KEYS.wsUrl);
  const savedBackend = storedBackend?.trim() || ENDPOINTS.origin;
  const savedWs = storedWs?.trim() || ENDPOINTS.ws;

  // Only what the user typed is state; an untouched field follows storage.
  const [draft, setDraft] = useState<{ backend?: string; ws?: string }>({});
  const backendUrl = draft.backend ?? savedBackend;
  const wsUrl = draft.ws ?? savedWs;
  const dirty = backendUrl !== savedBackend || wsUrl !== savedWs;

  const [errors, setErrors] = useState<{ backend?: string; ws?: string }>({});
  const [saved, setSaved] = useState(false);
  const announce = useAnnounce();

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // some browsers only warn when this is set
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (!saved) return;
    const timer = setTimeout(() => setSaved(false), 2500);
    return () => clearTimeout(timer);
  }, [saved]);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    const next = {
      backend: urlError(backendUrl, ["http:", "https:"], "http://localhost:8000") ?? undefined,
      ws: urlError(wsUrl, ["ws:", "wss:"], "ws://localhost:8000/ws") ?? undefined,
    };
    setErrors(next);
    if (next.backend || next.ws) return;
    setConnection({ backendUrl, wsUrl });
    setDraft({});
    setSaved(true);
    announce("Settings saved");
  };

  return (
    <div className="container mx-auto py-8 px-4 max-w-3xl">
      <h2 className="text-3xl font-bold mb-2">Settings</h2>
      <p className="text-muted-foreground mb-8">Configure the Weebot mission control UI.</p>

      <div className="space-y-6">
        {/* Connection */}
        <Card>
          <CardHeader>
            <CardTitle>Backend Connection</CardTitle>
            <CardDescription>
              URLs used by this UI to reach the Weebot backend server.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSave} noValidate className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="backend-url">Backend HTTP URL</Label>
                <Input
                  id="backend-url"
                  name="backend-url"
                  type="url"
                  autoComplete="off"
                  spellCheck={false}
                  value={backendUrl}
                  onChange={(e) => {
                    setDraft((d) => ({ ...d, backend: e.target.value }));
                    setErrors((er) => ({ ...er, backend: undefined }));
                  }}
                  placeholder={ENDPOINTS.origin}
                  aria-invalid={errors.backend ? true : undefined}
                  aria-describedby={errors.backend ? "backend-url-error" : "backend-url-hint"}
                />
                {errors.backend && (
                  <p id="backend-url-error" role="alert" className="text-sm text-status-error-fg">
                    {errors.backend}
                  </p>
                )}
                <p id="backend-url-hint" className="text-xs text-muted-foreground">
                  Used by REST requests from this browser. Leave it blank only if
                  the Next.js proxy is configured for your backend.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="ws-url">WebSocket URL</Label>
                <Input
                  id="ws-url"
                  name="ws-url"
                  type="url"
                  autoComplete="off"
                  spellCheck={false}
                  value={wsUrl}
                  onChange={(e) => {
                    setDraft((d) => ({ ...d, ws: e.target.value }));
                    setErrors((er) => ({ ...er, ws: undefined }));
                  }}
                  placeholder={ENDPOINTS.ws}
                  aria-invalid={errors.ws ? true : undefined}
                  aria-describedby={errors.ws ? "ws-url-error" : "ws-url-hint"}
                />
                {errors.ws && (
                  <p id="ws-url-error" role="alert" className="text-sm text-status-error-fg">
                    {errors.ws}
                  </p>
                )}
                <p id="ws-url-hint" className="text-xs text-muted-foreground">
                  Used directly by the browser for real-time event streaming.
                </p>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <Button type="submit">Save</Button>
                {saved && (
                  <span className="flex items-center gap-1 text-sm text-status-live-fg">
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                    Saved
                  </span>
                )}
              </div>
            </form>
          </CardContent>
        </Card>

        {/* Startup */}
        <Card>
          <CardHeader>
            <CardTitle>Starting the Backend</CardTitle>
            <CardDescription>Run these commands to start Weebot services.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">FastAPI Backend</p>
                <Badge variant="outline">Required</Badge>
              </div>
              <pre
                tabIndex={0}
                aria-label="Command to start the FastAPI backend"
                className="bg-muted p-3 rounded text-xs font-mono overflow-auto overscroll-contain"
                translate="no"
              >
                python -m weebot.interfaces.web.main
              </pre>
            </div>

            <Separator />

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">Next.js Dev Server (this UI)</p>
                <Badge variant="outline">This process</Badge>
              </div>
              <pre
                tabIndex={0}
                aria-label="Command to start the Next.js dev server"
                className="bg-muted p-3 rounded text-xs font-mono overflow-auto overscroll-contain"
                translate="no"
              >
                cd weebot-ui && npm run dev
              </pre>
            </div>

            <Separator />

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">MCP Server (optional)</p>
                <Badge variant="secondary">Optional</Badge>
              </div>
              <pre
                tabIndex={0}
                aria-label="Command to start the MCP server"
                className="bg-muted p-3 rounded text-xs font-mono overflow-auto overscroll-contain"
                translate="no"
              >
                python run_mcp.py
              </pre>
            </div>
          </CardContent>
        </Card>

        {/* Sub-pages */}
        <Card>
          <CardHeader>
            <CardTitle>Advanced Settings</CardTitle>
          </CardHeader>
          <CardContent>
            <Link
              href="/behavior?tab=settings"
              className="flex items-center justify-between p-3 rounded-lg border hover:bg-accent/50 transition-colors focus-ring"
            >
              <div>
                <p className="font-medium text-sm">Behavior Tracking</p>
                <p className="text-xs text-muted-foreground">
                  Configure filesystem monitoring and trust scoring
                </p>
              </div>
              <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
