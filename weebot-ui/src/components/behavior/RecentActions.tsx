"use client";

/**
 * Recent actions list with override capability.
 */

import { useState } from "react";
import { FilePlus, FileEdit, FileX, FileSymlink, Circle, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { RecentAction } from "@/hooks/useBehavior";

interface RecentActionsProps {
  actions: RecentAction[];
  onRefresh?: () => void;
}

const ACTION_ICON: Record<string, typeof Circle> = {
  created: FilePlus,
  modified: FileEdit,
  deleted: FileX,
  moved: FileSymlink,
};

const ACTION_COLOR: Record<string, string> = {
  created: "text-status-live",
  modified: "text-status-waiting",
  deleted: "text-status-error",
  moved: "text-cyan-500",
};

function formatTime(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "--:--";
  }
}

function formatPath(path: string): string {
  return path.split("/").slice(-2).join("/");
}

export function RecentActions({ actions, onRefresh }: RecentActionsProps) {
  const [selectedAction, setSelectedAction] = useState<RecentAction | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

  const handleOverride = async () => {
    if (!selectedAction || !overrideReason.trim()) return;
    setIsSubmitting(true);
    try {
      const res = await fetch(`${API_URL}/behavior/override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          timestamp: selectedAction.timestamp,
          reason: overrideReason,
        }),
      });
      if (res.ok) {
        setSelectedAction(null);
        setOverrideReason("");
        onRefresh?.();
      }
    } catch (e) {
      console.error("Failed to submit override:", e);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="rounded-lg bg-surface-1 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Recent Actions
        </div>
        <button
          onClick={onRefresh}
          className="rounded bg-surface-3 px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          Refresh
        </button>
      </div>

      <div className="flex max-h-[260px] flex-col gap-0.5 overflow-y-auto">
        {actions.length === 0 ? (
          <div className="py-5 text-center text-xs text-muted-foreground">No actions recorded</div>
        ) : (
          actions.map((action, index) => {
            const Icon = action.is_override ? AlertTriangle : ACTION_ICON[action.action] ?? Circle;
            const isSelected = selectedAction?.timestamp === action.timestamp;
            return (
              <button
                key={`${action.timestamp}-${index}`}
                onClick={() => setSelectedAction(action)}
                className={cn(
                  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[11px] transition-colors",
                  isSelected ? "bg-white/10" : "hover:bg-white/5"
                )}
              >
                <Icon
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    action.is_override ? "text-status-waiting" : ACTION_COLOR[action.action] ?? "text-muted-foreground"
                  )}
                />
                <span className="min-w-[40px] text-muted-foreground">{formatTime(action.timestamp)}</span>
                <span className={cn("flex-1 truncate", action.is_override ? "text-status-waiting" : "text-foreground/80")}>
                  {formatPath(action.path)}
                </span>
              </button>
            );
          })
        )}
      </div>

      {selectedAction && (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-sm rounded-xl bg-surface-2 p-6">
            <h4 className="mb-4 text-base font-semibold">Mark as Override</h4>

            <div className="mb-4">
              <div className="mb-2 text-xs text-muted-foreground">Action:</div>
              <div className="rounded bg-surface-1 px-3 py-2 font-mono text-xs text-foreground/80">
                {selectedAction.action} {selectedAction.path.slice(-40)}
              </div>
            </div>

            <div className="mb-4">
              <label className="mb-2 block text-xs text-muted-foreground">Reason for override:</label>
              <textarea
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder="Why was this action incorrect?"
                className="min-h-[80px] w-full resize-y rounded border border-border bg-surface-1 px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setSelectedAction(null)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={handleOverride}
                disabled={!overrideReason.trim() || isSubmitting}
              >
                {isSubmitting ? "Submitting..." : "Mark Override"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
