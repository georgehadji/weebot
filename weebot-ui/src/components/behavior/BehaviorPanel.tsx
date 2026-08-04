"use client";

/**
 * Main behavior tracking panel — combines trust bar, live feed, and
 * recent actions.
 */

import { ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { useBehavior, useBehaviorREST } from "@/hooks/useBehavior";
import { TrustBar } from "./TrustBar";
import { LiveFeed } from "./LiveFeed";
import { RecentActions } from "./RecentActions";

interface BehaviorPanelProps {
  sessionId?: string;
  showLiveFeed?: boolean;
  showRecentActions?: boolean;
  className?: string;
}

export function BehaviorPanel({
  sessionId,
  showLiveFeed = true,
  showRecentActions = true,
  className,
}: BehaviorPanelProps) {
  // Try WebSocket first, fallback to REST
  const ws = useBehavior(sessionId);
  const rest = useBehaviorREST(sessionId);

  // Use WebSocket data if connected, otherwise REST
  const trustScore = ws.trustScore || rest.trustScore;
  const recentActions = ws.recentActions.length > 0 ? ws.recentActions : rest.recentActions;
  const isConnected = ws.isConnected;
  const isLoading = rest.isLoading;

  return (
    <div className={cn("rounded-xl bg-surface-1 p-4", className)}>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-base font-semibold">
          <ShieldCheck className="h-4 w-4 text-agent" aria-hidden="true" />
          Behavior Monitor
        </h3>

        <div className="flex items-center gap-2">
          {isConnected ? (
            <span className="flex items-center gap-1 text-[11px] text-status-live">
              <span className="h-1.5 w-1.5 rounded-full bg-status-live" />
              Live
            </span>
          ) : isLoading ? (
            <span className="text-[11px] text-muted-foreground">Loading...</span>
          ) : (
            <span className="flex items-center gap-1 text-[11px] text-status-waiting">
              <span className="h-1.5 w-1.5 rounded-full bg-status-waiting" />
              Polling
            </span>
          )}
        </div>
      </div>

      <TrustBar trust={trustScore} />

      <div
        className="grid gap-4"
        style={{ gridTemplateColumns: showLiveFeed && showRecentActions ? "1fr 1fr" : "1fr" }}
      >
        {showLiveFeed && <LiveFeed events={ws.events} maxItems={30} />}
        {showRecentActions && <RecentActions actions={recentActions} onRefresh={rest.refreshAll} />}
      </div>

      <div className="mt-3 border-t pt-3 text-[11px] text-muted-foreground">
        {sessionId ? <span>Session: {sessionId.slice(0, 8)}...</span> : <span>Global behavior tracking</span>}
      </div>
    </div>
  );
}
