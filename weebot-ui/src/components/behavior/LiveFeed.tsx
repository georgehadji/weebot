"use client";

/**
 * Live event feed component.
 */

import { FilePlus, FileEdit, FileX, FileSymlink, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import { BehaviorEvent } from "@/hooks/useBehavior";

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
  "file.created": "text-status-live",
  "file.modified": "text-status-waiting",
  "file.deleted": "text-status-error",
  "file.moved": "text-cyan-500",
};

function formatTime(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleTimeString();
  } catch {
    return timestamp;
  }
}

function formatPath(path: string): string {
  const parts = path.split("/");
  if (parts.length > 3) {
    return ".../" + parts.slice(-2).join("/");
  }
  return path;
}

export function LiveFeed({ events, maxItems = 50 }: LiveFeedProps) {
  const displayEvents = events.slice(0, maxItems);

  return (
    <div className="max-h-[300px] overflow-y-auto rounded-lg bg-surface-1 p-3">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Live Feed ({events.length})
      </div>

      {displayEvents.length === 0 ? (
        <div className="py-5 text-center text-xs text-muted-foreground">No events yet...</div>
      ) : (
        <div className="flex flex-col gap-1">
          {displayEvents.map((event, index) => {
            const Icon = EVENT_ICON[event.type] ?? Circle;
            return (
              <div
                key={`${event.timestamp}-${index}`}
                className={cn(
                  "flex items-center gap-2 rounded px-2 py-1 font-mono text-xs",
                  index === 0 && "bg-white/5"
                )}
              >
                <Icon className={cn("h-3.5 w-3.5 w-4 shrink-0", EVENT_COLOR[event.type] ?? "text-muted-foreground")} />
                <span className="min-w-[60px] text-muted-foreground">{formatTime(event.timestamp)}</span>
                <span className="flex-1 truncate text-foreground/80">{formatPath(event.path)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
