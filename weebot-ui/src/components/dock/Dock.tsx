"use client";

/**
 * MissionDock — compound component: parent owns the active-tab state,
 * children consume it via the shared Tabs primitive context.
 *
 * Auto-bound to `sessionId` — no manual "enter a session ID" box like the
 * old Dashboard's Plan Visualization tab had.
 */

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PlanTab } from "./PlanTab";
import { ToolsTab } from "./ToolsTab";
import { CostTab } from "./CostTab";
import { TrustTab } from "./TrustTab";

interface MissionDockProps {
  sessionId: string;
}

export function MissionDock({ sessionId }: MissionDockProps) {
  return (
    <Tabs defaultValue="plan" className="flex h-full flex-col gap-0">
      <TabsList className="m-2 shrink-0">
        <TabsTrigger value="plan">Plan</TabsTrigger>
        <TabsTrigger value="tools">Tools</TabsTrigger>
        <TabsTrigger value="cost">Cost</TabsTrigger>
        <TabsTrigger value="trust">Trust</TabsTrigger>
      </TabsList>
      <div className="flex-1 overflow-y-auto">
        <TabsContent value="plan" className="m-0">
          <PlanTab sessionId={sessionId} />
        </TabsContent>
        <TabsContent value="tools" className="m-0">
          <ToolsTab sessionId={sessionId} />
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
