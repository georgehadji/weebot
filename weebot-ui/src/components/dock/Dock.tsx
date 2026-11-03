"use client";

/**
 * MissionDock — compound component: parent owns the active-tab state,
 * children consume it via the shared Tabs primitive context.
 *
 * Auto-bound to `sessionId` — no manual "enter a session ID" box like the
 * old Dashboard's Plan Visualization tab had.
 */

import { Suspense } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUrlState } from "@/hooks/useUrlState";
import { PlanTab } from "./PlanTab";
import { ToolsTab } from "./ToolsTab";
import { CostTab } from "./CostTab";
import { TrustTab } from "./TrustTab";

interface MissionDockProps {
  sessionId: string;
}

const DOCK_TABS = ["plan", "tools", "cost", "trust"];

/** useUrlState reads the query string, which Next 16 only allows below a Suspense boundary. */
export function MissionDock({ sessionId }: MissionDockProps) {
  return (
    <Suspense fallback={<div role="status" className="p-4 text-xs text-muted-foreground">Loading…</div>}>
      <DockTabs sessionId={sessionId} />
    </Suspense>
  );
}

function DockTabs({ sessionId }: MissionDockProps) {
  // The tab lives in the URL (?dock=), so it survives the sheet remounting and a reload.
  const [param, setTab] = useUrlState("dock", "plan");
  const tab = DOCK_TABS.includes(param) ? param : "plan";
  return (
    <Tabs value={tab} onValueChange={(next) => setTab(String(next))} className="flex h-full flex-col gap-0">
      <TabsList className="m-2 shrink-0">
        <TabsTrigger value="plan">Plan</TabsTrigger>
        <TabsTrigger value="tools">Tools</TabsTrigger>
        <TabsTrigger value="cost">Cost</TabsTrigger>
        <TabsTrigger value="trust">Trust</TabsTrigger>
      </TabsList>
      <div className="flex-1 overflow-y-auto overscroll-contain">
        <TabsContent value="plan" className="m-0">
          {/* Keyed so switching sessions remounts with fresh state instead
              of carrying the previous session's plan or tool calls. */}
          <PlanTab key={sessionId} sessionId={sessionId} />
        </TabsContent>
        <TabsContent value="tools" className="m-0">
          <ToolsTab key={sessionId} sessionId={sessionId} />
        </TabsContent>
        <TabsContent value="cost" className="m-0">
          <CostTab />
        </TabsContent>
        <TabsContent value="trust" className="m-0">
          <TrustTab sessionId={sessionId} />
        </TabsContent>
      </div>
    </Tabs>
  );
}
