"use client";

/**
 * Trust score display component.
 */

import { cn } from "@/lib/utils";
import { TrustScore } from "@/hooks/useBehavior";

interface TrustBarProps {
  trust: TrustScore | null;
}

function trustClass(percentage: number): { border: string; text: string; bar: string } {
  if (percentage >= 90) return { border: "border-status-live", text: "text-status-live", bar: "bg-status-live" };
  if (percentage >= 70) return { border: "border-status-waiting", text: "text-status-waiting", bar: "bg-status-waiting" };
  return { border: "border-status-error", text: "text-status-error", bar: "bg-status-error" };
}

const STATUS_TEXT: Record<string, string> = {
  trusted: "Trusted",
  review: "Review Needed",
  supervision: "Requires Supervision",
};

export function TrustBar({ trust }: TrustBarProps) {
  if (!trust) {
    return (
      <div className="mb-4 rounded-lg bg-surface-2 px-4 py-3 text-sm text-muted-foreground">
        Loading trust score...
      </div>
    );
  }

  const colors = trustClass(trust.score_percentage);

  return (
    <div className="mb-4 rounded-lg bg-surface-2 px-4 py-3">
      <div className="flex items-center gap-4">
        <div
          className={cn(
            "flex h-[60px] w-[60px] shrink-0 items-center justify-center rounded-full border-[3px] text-xl font-bold",
            colors.border,
            colors.text
          )}
        >
          {trust.score_percentage}%
        </div>

        <div className="flex-1">
          <div className={cn("text-base font-semibold", colors.text)}>
            {STATUS_TEXT[trust.status] ?? "Unknown"}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {trust.total_actions.toLocaleString()} actions · {trust.overrides} overrides
          </div>
        </div>

        <div className="w-[120px] shrink-0">
          <div className="h-2 overflow-hidden rounded-full bg-surface-3">
            <div
              className={cn("h-full transition-[width] duration-base ease-console", colors.bar)}
              style={{ width: `${trust.score_percentage}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
