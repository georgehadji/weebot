"use client";

/**
 * ConsoleShell — the persistent 3-pane mission-center layout, mounted once by the
 * `(console)` route group so the rail, its data and its subscription survive navigation.
 *
 * Mobile-first: one column with the rail and dock as side sheets; `md:` and up is a CSS grid
 * with all three panes visible. The dock is a slot: the session page names the session
 * (`useShellSlots({ dockSessionId })`) and this layout renders its details.
 */

import { useState } from "react";
import { usePathname } from "next/navigation";
import { PanelLeft, PanelRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MissionDock } from "@/components/dock/Dock";
import { ResponsivePanel } from "@/components/shell/ResponsivePanel";
import { SessionRail } from "@/components/shell/SessionRail";
import { useShell } from "@/providers/ShellProvider";

export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { slots } = useShell();
  // A sheet is open "at" a path, so navigating from inside it closes it without an effect.
  const [railPath, setRailPath] = useState<string | null>(null);
  const [dockPath, setDockPath] = useState<string | null>(null);
  const dockSessionId = slots.dockSessionId;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b bg-surface-1 px-2 py-1 md:hidden">
        <Button variant="ghost" size="sm" onClick={() => setRailPath(pathname)} className="gap-1 text-xs">
          <PanelLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Sessions
        </Button>
        {dockSessionId && (
          <Button variant="ghost" size="sm" onClick={() => setDockPath(pathname)} className="ml-auto gap-1 text-xs">
            <PanelRight className="h-3.5 w-3.5" aria-hidden="true" />
            Details
          </Button>
        )}
      </div>

      <div className="flex min-h-0 flex-1 md:grid md:grid-cols-[var(--rail-w)_1fr_auto]">
        <ResponsivePanel
          label="Sessions"
          side="left"
          open={railPath === pathname}
          onOpenChange={(open) => setRailPath(open ? pathname : null)}
        >
          <SessionRail />
        </ResponsivePanel>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">{children}</div>

        {dockSessionId && (
          <ResponsivePanel
            label="Session details"
            side="right"
            open={dockPath === pathname}
            onOpenChange={(open) => setDockPath(open ? pathname : null)}
            inlineClassName="md:w-dock md:shrink-0 md:border-l"
          >
            <MissionDock sessionId={dockSessionId} />
          </ResponsivePanel>
        )}
      </div>
    </div>
  );
}
