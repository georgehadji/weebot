"use client";

/**
 * Behavior Tracking — live monitor + settings, consolidated.
 *
 * Previously two separate routes (/behavior for viewing, /settings/behavior
 * for configuring) that duplicated the "what is behavior tracking" framing
 * and forced a navigation between them to go from watching to configuring.
 */

import { Suspense, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUrlState } from "@/hooks/useUrlState";
import { authHeaders, getApiBase } from "@/lib/api";
import { useToast } from "@/providers/ToastProvider";
import { BehaviorPanel } from "@/components/behavior";

const newDemoId = () => `demo-${Date.now().toString(36)}`;

function MonitorTab() {
  const [sessionId, setSessionId] = useState(newDemoId);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="pt-4">
          <Label htmlFor="behavior-session-id" className="mb-2 text-muted-foreground">
            Session ID
          </Label>
          <div className="flex gap-2">
            <Input
              id="behavior-session-id"
              name="session-id"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              className="h-10 flex-1 font-mono"
            />
            <Button variant="outline" onClick={() => setSessionId(newDemoId())}>
              Generate Demo ID
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
            <pre
              tabIndex={0}
              role="region"
              aria-label="Behavior CLI commands"
              translate="no"
              className="overflow-auto overscroll-contain rounded-md bg-surface-1 p-4 text-xs"
            >
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
  const { toast } = useToast();
  const downloadSelfKnowledge = async () => {
    try {
      const res = await fetch(`${getApiBase()}/behavior/self-knowledge`, { headers: authHeaders() });
      if (!res.ok) throw new Error(`The server answered ${res.status}`);
      const data = await res.json();
      const url = URL.createObjectURL(new Blob([data.content], { type: "text/markdown" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "WEEBOT_SELF.md";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast({
        title: "Couldn't download the self-knowledge file",
        description: `${e instanceof Error ? e.message : "Unknown error"}. Check that the backend is running, then try again.`,
        variant: "error",
      });
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="divide-y pt-4">
          <div className="py-4">
            <h2 className="font-medium">Storage Location</h2>
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
          <pre
            tabIndex={0}
            role="region"
            aria-label="Environment variable examples"
            translate="no"
            className="overflow-auto overscroll-contain rounded-md bg-surface-1 p-4 text-xs"
          >
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
  const [tab, setTab] = useUrlState("tab", "monitor");

  return (
    <Tabs value={tab === "settings" ? "settings" : "monitor"} onValueChange={(next) => setTab(String(next))}>
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
      <h2 className="mb-6 flex items-center gap-2 text-3xl font-bold">
        <ShieldCheck className="h-7 w-7 text-agent" aria-hidden="true" />
        Behavior Tracking
      </h2>

      <Suspense
        fallback={
          <div role="status" className="text-sm text-muted-foreground">
            Loading…
          </div>
        }
      >
        <BehaviorTabs />
      </Suspense>
    </div>
  );
}
