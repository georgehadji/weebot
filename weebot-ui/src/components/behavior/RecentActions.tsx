"use client";

/**
 * Recent actions list with override capability.
 */

import { useState } from "react";
import { FilePlus, FileEdit, FileX, FileSymlink, Circle, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RecentAction } from "@/hooks/useBehavior";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useIntlContext } from "@/hooks/useIntlContext";
import { formatDate } from "@/lib/format";
import { authHeaders, getApiBase } from "@/lib/api";

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
  created: "text-status-live-fg",
  modified: "text-status-waiting-fg",
  deleted: "text-status-error-fg",
  moved: "text-agent",
};

const ACTION_LABEL: Record<string, string> = {
  created: "Created",
  modified: "Modified",
  deleted: "Deleted",
  moved: "Moved",
};

function formatPath(path: string): string {
  return path.split("/").slice(-2).join("/");
}

/**
 * The list is replaced on every poll, so object identity and position say nothing about a row.
 * The timestamp is what the backend identifies an action by; the occurrence count only
 * separates rows that share timestamp, action and path exactly.
 */
function withKeys(actions: RecentAction[]): { key: string; action: RecentAction }[] {
  const seen = new Map<string, number>();
  return actions.map((action) => {
    const base = `${action.timestamp}|${action.action}|${action.path}`;
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return { key: n ? `${base}#${n}` : base, action };
  });
}

export function RecentActions({ actions, onRefresh }: RecentActionsProps) {
  const ctx = useIntlContext();
  const [selectedAction, setSelectedAction] = useState<RecentAction | null>(null);
  const [overrideReason, setOverrideReason] = useState("");

  const submit = useAsyncAction(async () => {
    if (!selectedAction || !overrideReason.trim()) return;
    let res: Response;
    try {
      res = await fetch(`${getApiBase()}/behavior/override`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          timestamp: selectedAction.timestamp,
          reason: overrideReason,
        }),
      });
    } catch (e) {
      console.error("Failed to submit override:", e);
      throw new Error("Could not reach the backend. Check that it is running, then try again");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      const why = typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`;
      throw new Error(`${why}. Try again, or refresh the list and pick the action again`);
    }
  });

  const close = () => {
    setSelectedAction(null);
    setOverrideReason("");
    submit.reset();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (await submit.run()) {
      close();
      onRefresh?.();
    }
  };

  return (
    <div className="rounded-lg bg-surface-1 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Recent Actions
        </div>
        <Button variant="ghost" size="sm" onClick={onRefresh} className="h-7 bg-surface-3 px-2 text-xs text-muted-foreground">
          Refresh
        </Button>
      </div>

      <div className="flex max-h-[260px] flex-col gap-0.5 overflow-y-auto overscroll-contain">
        {actions.length === 0 ? (
          <div className="py-5 text-center text-xs text-muted-foreground">No actions recorded</div>
        ) : (
          withKeys(actions).map(({ key, action }) => {
            const Icon = action.is_override ? AlertTriangle : ACTION_ICON[action.action] ?? Circle;
            const isSelected = selectedAction?.timestamp === action.timestamp;
            return (
              <Button
                key={key}
                variant="ghost"
                onClick={() => setSelectedAction(action)}
                className={cn(
                  "cv-auto-sm h-auto w-full justify-start gap-2 rounded px-2 py-1.5 text-left font-mono text-xs font-normal",
                  isSelected && "bg-muted"
                )}
              >
                <Icon
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    action.is_override ? "text-status-waiting-fg" : ACTION_COLOR[action.action] ?? "text-muted-foreground"
                  )}
                  aria-hidden="true"
                />
                <span className="sr-only">
                  {action.is_override ? "Override, " : ""}
                  {ACTION_LABEL[action.action] ?? action.action}
                </span>
                <span className="min-w-[5ch] shrink-0 tabular-nums text-muted-foreground">
                  {formatDate(action.timestamp, ctx, { hour: "2-digit", minute: "2-digit" }) ?? "--:--"}
                </span>
                <span
                  translate="no"
                  title={action.path}
                  className={cn("min-w-0 flex-1 truncate", action.is_override ? "text-status-waiting-fg" : "text-foreground/80")}
                >
                  {formatPath(action.path)}
                </span>
              </Button>
            );
          })
        )}
      </div>

      <Dialog
        open={selectedAction !== null}
        onOpenChange={(open) => {
          if (!open && !submit.pending) close();
        }}
      >
        <DialogContent>
          <DialogTitle>Mark as Override</DialogTitle>
          <form onSubmit={handleSubmit} className="grid gap-4">
            <div>
              <div className="mb-2 text-xs text-muted-foreground">Action:</div>
              <div className="flex min-w-0 gap-1 rounded bg-surface-1 px-3 py-2 font-mono text-xs text-foreground/80">
                <span>{selectedAction?.action}</span>
                {/* rtl keeps the end of a long path visible; <bdi> stops it reordering the slashes. */}
                <span translate="no" title={selectedAction?.path} className="min-w-0 flex-1 truncate text-left [direction:rtl]">
                  <bdi>{selectedAction?.path}</bdi>
                </span>
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="override-reason" className="text-xs text-muted-foreground">
                Reason for override
              </Label>
              <textarea
                id="override-reason"
                name="reason"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder="Why was this action incorrect?"
                className="min-h-[80px] w-full resize-y rounded border border-border bg-surface-1 px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground focus-ring"
              />
            </div>

            {submit.state.status === "error" && (
              <p role="alert" className="text-xs text-status-error-fg">
                {submit.state.error}
              </p>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" size="sm" onClick={close} disabled={submit.pending}>
                Cancel
              </Button>
              <Button
                type="submit"
                variant="destructive"
                size="sm"
                loading={submit.pending}
                disabled={!overrideReason.trim() && !submit.pending}
              >
                {submit.pending ? "Submitting…" : "Mark Override"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
