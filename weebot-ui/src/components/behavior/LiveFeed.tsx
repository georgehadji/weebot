"use client";

/**
 * Live event feed component.
 */

import { FilePlus, FileEdit, FileX, FileSymlink, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import { BehaviorEvent } from "@/hooks/useBehavior";
import { useIntlContext } from "@/hooks/useIntlContext";
import { formatNumber, formatTime } from "@/lib/format";

interface LiveFeedProps {
  events: BehaviorEvent[];
  maxItems?: number;
}

const EVENT_ICON: Record<string, typeof Circle> = {
  "file.created": FilePlus,
  "file.modified": FileEdit,
  "file.deleted": FileX,
  "file.moved": FileSymlink,
};

const EVENT_COLOR: Record<string, string> = {
  "file.created": "text-status-live-fg",
  "file.modified": "text-status-waiting-fg",
  "file.deleted": "text-status-error-fg",
  "file.moved": "text-agent",
};

const EVENT_LABEL: Record<string, string> = {
  "file.created": "Created",
  "file.modified": "Modified",
  "file.deleted": "Deleted",
  "file.moved": "Moved",
};

function formatPath(path: string): string {
  const parts = path.split("/");
  if (parts.length > 3) {
    return "…/" + parts.slice(-2).join("/");
  }
  return path;
}

// The feed slides (new events go on the front), so an index would remount every row on each
// event. Each event object keeps its identity, so its key is assigned once, the first time the
// feed sees it.
const eventKeys = new WeakMap<object, number>();
let nextEventKey = 0;
function keyOf(event: BehaviorEvent): number {
  let key = eventKeys.get(event);
  if (key === undefined) {
    key = nextEventKey++;
    eventKeys.set(event, key);
  }
  return key;
}

export function LiveFeed({ events, maxItems = 50 }: LiveFeedProps) {
  const ctx = useIntlContext();
  const displayEvents = events.slice(0, maxItems);

  return (
    <div className="max-h-[300px] overflow-y-auto overscroll-contain rounded-lg bg-surface-1 p-3">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Live Feed (<span className="tabular-nums">{formatNumber(events.length, ctx)}</span>)
      </div>

      {/* Always mounted: a live region that appears together with its first row is not announced. */}
      <div role="log" aria-label="Live file events" className="flex flex-col gap-1">
        {displayEvents.length === 0 ? (
          <div className="py-5 text-center text-xs text-muted-foreground">No events yet…</div>
        ) : (
          displayEvents.map((event, index) => {
            const Icon = EVENT_ICON[event.type] ?? Circle;
            return (
              <div
                key={keyOf(event)}
                className={cn(
                  "cv-auto-sm flex items-center gap-2 rounded px-2 py-1 font-mono text-xs",
                  index === 0 && "bg-muted"
                )}
              >
                <Icon
                  className={cn("h-3.5 w-3.5 shrink-0", EVENT_COLOR[event.type] ?? "text-muted-foreground")}
                  aria-hidden="true"
                />
                <span className="sr-only">{EVENT_LABEL[event.type] ?? "Changed"}</span>
                <span className="min-w-[11ch] shrink-0 tabular-nums text-muted-foreground">
                  {formatTime(event.timestamp, ctx) ?? "--:--"}
                </span>
                <span translate="no" title={event.path} className="min-w-0 flex-1 truncate text-foreground/80">
                  {formatPath(event.path)}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
