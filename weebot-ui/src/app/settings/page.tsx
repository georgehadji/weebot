"use client";

import { useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { CheckCircle2, ExternalLink } from "lucide-react";

export default function SettingsPage() {
  const [backendUrl, setBackendUrl] = useState(
    typeof window !== "undefined"
      ? localStorage.getItem("weebot_backend_url") || "http://localhost:8000"
      : "http://localhost:8000"
  );
  const [wsUrl, setWsUrl] = useState(
    typeof window !== "undefined"
      ? localStorage.getItem("weebot_ws_url") || "ws://localhost:8000/ws"
      : "ws://localhost:8000/ws"
  );
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    localStorage.setItem("weebot_backend_url", backendUrl);
    localStorage.setItem("weebot_ws_url", wsUrl);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <div className="container mx-auto py-8 px-4 max-w-3xl">
      <h1 className="text-3xl font-bold mb-2">Settings</h1>
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
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="backend-url">Backend HTTP URL</Label>
              <Input
                id="backend-url"
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                placeholder="http://localhost:8000"
              />
              <p className="text-xs text-muted-foreground">
                Used by the Next.js API proxy to forward REST requests.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="ws-url">WebSocket URL</Label>
              <Input
                id="ws-url"
                value={wsUrl}
                onChange={(e) => setWsUrl(e.target.value)}
                placeholder="ws://localhost:8000/ws"
              />
              <p className="text-xs text-muted-foreground">
                Used directly by the browser for real-time event streaming.
              </p>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <Button onClick={handleSave}>Save</Button>
              {saved && (
                <span className="flex items-center gap-1 text-sm text-green-600">
                  <CheckCircle2 className="h-4 w-4" />
                  Saved
                </span>
              )}
            </div>
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
                <Label>FastAPI Backend</Label>
                <Badge variant="outline">Required</Badge>
              </div>
              <pre className="bg-muted p-3 rounded text-xs font-mono overflow-auto">
                python -m weebot.interfaces.web.main
              </pre>
            </div>

            <Separator />

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Next.js Dev Server (this UI)</Label>
                <Badge variant="outline">This process</Badge>
              </div>
              <pre className="bg-muted p-3 rounded text-xs font-mono overflow-auto">
                cd weebot-ui && npm run dev
              </pre>
            </div>

            <Separator />

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>MCP Server (optional)</Label>
                <Badge variant="secondary">Optional</Badge>
              </div>
              <pre className="bg-muted p-3 rounded text-xs font-mono overflow-auto">
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
              href="/settings/behavior"
              className="flex items-center justify-between p-3 rounded-lg border hover:bg-accent/50 transition-colors"
            >
              <div>
                <p className="font-medium text-sm">Behavior Tracking</p>
                <p className="text-xs text-muted-foreground">
                  Configure filesystem monitoring and trust scoring
                </p>
              </div>
              <ExternalLink className="h-4 w-4 text-muted-foreground" />
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
