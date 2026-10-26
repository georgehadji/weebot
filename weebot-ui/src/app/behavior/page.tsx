"use client";

/**
 * Behavior Tracking — live monitor + settings, consolidated.
 *
 * Previously two separate routes (/behavior for viewing, /settings/behavior
 * for configuring) that duplicated the "what is behavior tracking" framing
 * and forced a navigation between them to go from watching to configuring.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { authHeaders } from "@/lib/api";
import { BehaviorPanel } from "@/components/behavior";

function MonitorTab() {
  const [sessionId, setSessionId] = useState(() => `demo-${Date.now().toString(36)}`);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="pt-4">
          <label htmlFor="behavior-session-id" className="mb-2 block text-sm text-muted-foreground">
            Session ID
          </label>
          <div className="flex gap-2">
            <input
              id="behavior-session-id"
              type="text"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              className="flex-1 rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
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
              className="font-medium text-foreground underline underline-offset-2 hover:no-underline"
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
            <pre tabIndex={0} aria-label="Example commands" className="overflow-auto rounded-md bg-surface-1 p-4 text-xs">
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
  // Tracking is configured by the environment variables below; there is no
  // settings API (the old toggles posted to a route that did not exist).
  const downloadSelfKnowledge = () => {
    fetch("/api/behavior/self-knowledge", { headers: authHeaders() })
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
        <Button variant="outline" onClick={downloadSelfKnowledge}>
          Download Self-Knowledge
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Settings (environment variables)</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-sm text-muted-foreground">
            Tracking is on by default. Set these before starting the backend to change it.
          </p>
          <pre tabIndex={0} aria-label="Example commands" className="overflow-auto rounded-md bg-surface-1 p-4 text-xs">
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
