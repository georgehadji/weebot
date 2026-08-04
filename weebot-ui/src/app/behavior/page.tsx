"use client";

/**
 * Behavior Tracking — live monitor + settings, consolidated.
 *
 * Previously two separate routes (/behavior for viewing, /settings/behavior
 * for configuring) that duplicated the "what is behavior tracking" framing
 * and forced a navigation between them to go from watching to configuring.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { BehaviorPanel } from "@/components/behavior";

function MonitorTab() {
  const [sessionId, setSessionId] = useState(`demo-${Date.now().toString(36)}`);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="pt-4">
          <label className="mb-2 block text-sm text-muted-foreground">Session ID</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              className="flex-1 rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <Button variant="outline" onClick={() => setSessionId(`demo-${Date.now().toString(36)}`)}>
              New Session
            </Button>
          </div>
        </CardContent>
      </Card>

      <BehaviorPanel sessionId={sessionId} />

      <Card>
        <CardHeader>
          <CardTitle>About Behavior Tracking</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            Inspired by{" "}
            <a
              href="https://github.com/Tetrahedroned/iterance"
              target="_blank"
              rel="noopener noreferrer"
              className="text-agent hover:underline"
            >
              Iterance
            </a>{" "}
            — a behavioral witness layer that creates an immutable record of agent actions.
          </p>
          <div>
            <h3 className="mb-2 font-medium text-foreground">Key features</h3>
            <ul className="list-disc space-y-1 pl-5">
              <li>Real-time filesystem monitoring</li>
              <li>Git-backed ledger — every action committed for auditability</li>
              <li>Evidence-based trust scoring from override history</li>
              <li>Override tracking to improve future behavior</li>
              <li>
                Self-knowledge via <code className="font-mono">~/.weebot/WEEBOT_SELF.md</code>
              </li>
            </ul>
          </div>
          <div>
            <h3 className="mb-2 font-medium text-foreground">CLI commands</h3>
            <pre className="overflow-auto rounded-md bg-surface-1 p-4 text-xs">
{`weebot behavior watch ./my-project --session-id abc123
weebot behavior trust
weebot behavior log --count 20
weebot behavior override --timestamp "..." --reason "..."
weebot behavior reflect`}
            </pre>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function SettingsTab() {
  const [enabled, setEnabled] = useState(true);
  const [autoStart, setAutoStart] = useState(true);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch("/api/behavior/settings")
      .then((res) => res.json())
      .then((data) => {
        setEnabled(data.enabled ?? true);
        setAutoStart(data.auto_start ?? true);
      })
      .catch(() => {
        // Use defaults if API not available
      });
  }, []);

  const saveSettings = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/behavior/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, auto_start: autoStart }),
      });
      if (res.ok) {
        setMessage("Settings saved!");
        setTimeout(() => setMessage(""), 3000);
      }
    } catch {
      setMessage("Failed to save settings");
    } finally {
      setLoading(false);
    }
  };

  const downloadSelfKnowledge = () => {
    fetch("/api/behavior/self-knowledge")
      .then((res) => res.json())
      .then((data) => {
        const blob = new Blob([data.content], { type: "text/markdown" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "WEEBOT_SELF.md";
        a.click();
      });
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="divide-y pt-4">
          <div className="flex items-center justify-between py-4">
            <div>
              <h3 className="font-medium">Enable Behavior Tracking</h3>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Record all filesystem actions during agent sessions
              </p>
            </div>
            <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Enable behavior tracking" />
          </div>

          <div className="flex items-center justify-between py-4" style={{ opacity: enabled ? 1 : 0.5 }}>
            <div>
              <h3 className="font-medium">Auto-start with Sessions</h3>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Automatically start tracking when a new session begins
              </p>
            </div>
            <Switch
              checked={autoStart && enabled}
              onCheckedChange={setAutoStart}
              disabled={!enabled}
              aria-label="Auto-start tracking with sessions"
            />
          </div>

          <div className="py-4">
            <h3 className="font-medium">Storage Location</h3>
            <code className="mt-2 block rounded-md bg-surface-1 p-3 text-sm text-muted-foreground">
              ~/.weebot/ledger/
            </code>
            <p className="mt-2 text-xs text-muted-foreground">
              Behavior data is stored locally in a git-backed ledger
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="flex gap-3">
        <Button onClick={saveSettings} disabled={loading}>
          {loading ? "Saving..." : "Save Settings"}
        </Button>
        <Button variant="outline" onClick={downloadSelfKnowledge}>
          Download Self-Knowledge
        </Button>
      </div>

      {message && (
        <div
          className={
            message.includes("saved")
              ? "rounded-md bg-status-live/10 px-4 py-3 text-sm text-status-live"
              : "surface-error rounded-md px-4 py-3 text-sm"
          }
        >
          {message}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">CLI Environment Variables</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="overflow-auto rounded-md bg-surface-1 p-4 text-xs">
{`export WEEBOT_BEHAVIOR_TRACKING=false
export WEEBOT_LEDGER_DIR=/path/to/ledger
export WEEBOT_EXTRA_IGNORE="*.log,dist/"`}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

/** Reads ?tab=, so it must sit under a Suspense boundary — useSearchParams()
 *  opts the subtree into client-side rendering and Next fails the production
 *  build when it is not wrapped. */
function BehaviorTabs() {
  const searchParams = useSearchParams();
  const initialTab = searchParams.get("tab") === "settings" ? "settings" : "monitor";

  return (
    <Tabs defaultValue={initialTab}>
      <TabsList className="mb-6">
        <TabsTrigger value="monitor">Monitor</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
      <TabsContent value="monitor">
        <MonitorTab />
      </TabsContent>
      <TabsContent value="settings">
        <SettingsTab />
      </TabsContent>
    </Tabs>
  );
}

export default function BehaviorPage() {
  return (
    <div className="container mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-6 flex items-center gap-2 text-3xl font-bold">
        <ShieldCheck className="h-7 w-7 text-agent" />
        Behavior Tracking
      </h1>

      <Suspense fallback={<div className="text-sm text-muted-foreground">Loading…</div>}>
        <BehaviorTabs />
      </Suspense>
    </div>
  );
}
