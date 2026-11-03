"use client";

/**
 * Main behavior tracking panel — combines trust bar, live feed, and
 * recent actions.
 */

import { useEffect, useRef } from "react";
import { ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { useBehavior, useBehaviorREST } from "@/hooks/useBehavior";
import { useAnnounce } from "@/providers/AnnouncerProvider";
import { TrustBar } from "./TrustBar";
import { LiveFeed } from "./LiveFeed";
import { RecentActions } from "./RecentActions";

interface BehaviorPanelProps {
  sessionId?: string;
  showLiveFeed?: boolean;
  showRecentActions?: boolean;
  className?: string;
}

type Link = "live" | "loading" | "unavailable" | "polling";

const LINK_ANNOUNCEMENT: Record<Exclude<Link, "loading">, string> = {
  live: "Behavior monitor is live",
  polling: "Behavior monitor is polling",
  unavailable: "Behavior monitor is unavailable",
};

export function BehaviorPanel({
  sessionId,
  showLiveFeed = true,
  showRecentActions = true,
  className,
}: BehaviorPanelProps) {
  const ws = useBehavior(sessionId);
  const rest = useBehaviorREST(sessionId);

  // REST is polled and complete; the socket's trust frame has no status and its recent list is
  // a one-off snapshot, so each is only the fallback for when REST has nothing.
  const trustScore = rest.trustScore || ws.trustScore;
  const recentActions = rest.recentActions.length > 0 ? rest.recentActions : ws.recentActions;
  const isConnected = ws.isConnected;
  const isLoading = rest.isLoading;

  const link: Link = isConnected ? "live" : isLoading ? "loading" : rest.isUnavailable ? "unavailable" : "polling";
  const announce = useAnnounce();
  const previousLink = useRef(link);
  // Only a change between settled states is news; the first render and the load that follows
  // it (or a manual refresh) are not.
  useEffect(() => {
    const was = previousLink.current;
    previousLink.current = link;
    if (was !== link && was !== "loading" && link !== "loading") announce(LINK_ANNOUNCEMENT[link]);
  }, [link, announce]);

  return (
    <section
      aria-label={sessionId ? `Behavior monitor, session ${sessionId.slice(0, 8)}` : "Behavior monitor, all sessions"}
      className={cn("rounded-xl bg-surface-1 p-4", className)}
    >
      <div className="mb-4 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-base font-semibold">
          <ShieldCheck className="h-4 w-4 text-agent" aria-hidden="true" />
          Behavior Monitor
        </h3>

        <div className="flex items-center gap-2">
          {isConnected ? (
            <span className="flex items-center gap-1 text-xs text-status-live-fg">
              <span className="h-1.5 w-1.5 rounded-full bg-status-live" aria-hidden="true" />
              Live
            </span>
          ) : isLoading ? (
            <span className="text-xs text-muted-foreground">Loading…</span>
          ) : rest.isUnavailable ? (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-status-idle" aria-hidden="true" />
              Unavailable
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-status-waiting-fg">
              <span className="h-1.5 w-1.5 rounded-full bg-status-waiting" aria-hidden="true" />
              Polling
            </span>
          )}
        </div>
      </div>

      <TrustBar trust={trustScore} />

      {/* minmax(0,1fr), which grid-cols-N is, lets a long path shrink instead of widening the column. */}
      <div className={cn("grid gap-4", showLiveFeed && showRecentActions ? "grid-cols-2" : "grid-cols-1")}>
        {showLiveFeed && <LiveFeed events={ws.events} maxItems={30} />}
        {showRecentActions && <RecentActions actions={recentActions} onRefresh={rest.refreshAll} />}
      </div>

      <div className="mt-3 border-t pt-3 text-xs text-muted-foreground">
        {sessionId ? (
          <span>
            Session: <span translate="no">{sessionId.slice(0, 8)}</span>…
          </span>
        ) : (
          <span>Global behavior tracking</span>
        )}
      </div>
    </section>
  );
}
