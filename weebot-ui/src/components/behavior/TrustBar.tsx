"use client";

/**
 * Trust score display component.
 */

import { cn } from "@/lib/utils";
import { TrustScore } from "@/hooks/useBehavior";
import { useIntlContext } from "@/hooks/useIntlContext";
import { formatPercent, plural } from "@/lib/format";

interface TrustBarProps {
  trust: TrustScore | null;
}

function trustClass(percentage: number): { border: string; text: string; bar: string } {
  if (percentage >= 90) return { border: "border-status-live", text: "text-status-live-fg", bar: "bg-status-live" };
  if (percentage >= 70) return { border: "border-status-waiting", text: "text-status-waiting-fg", bar: "bg-status-waiting" };
  return { border: "border-status-error", text: "text-status-error-fg", bar: "bg-status-error" };
}

const STATUS_TEXT: Record<string, string> = {
  trusted: "Trusted",
  review: "Review Needed",
  supervision: "Requires Supervision",
};

/** The socket's first frame can omit counts; they read 0, not NaN. */
const finite = (n: number) => (Number.isFinite(n) ? n : 0);

export function TrustBar({ trust }: TrustBarProps) {
  const ctx = useIntlContext();

  if (!trust) {
    return (
      <div role="status" className="mb-4 rounded-lg bg-surface-2 px-4 py-3 text-sm text-muted-foreground">
        Loading trust score…
      </div>
    );
  }

  // The socket's first frame can lack score_percentage; that reads as 0 rather than NaN.
  const percentage = Number.isFinite(trust.score_percentage)
    ? Math.min(100, Math.max(0, trust.score_percentage))
    : 0;
  const colors = trustClass(percentage);

  return (
    <div className="mb-4 rounded-lg bg-surface-2 px-4 py-3">
      <div className="flex items-center gap-4">
        <div
          className={cn(
            "flex h-[60px] w-[60px] shrink-0 items-center justify-center rounded-full border-[3px] text-xl font-bold tabular-nums",
            colors.border,
            colors.text
          )}
        >
          {formatPercent(percentage, ctx)}
        </div>

        <div className="flex-1">
          <div className={cn("text-base font-semibold", colors.text)}>
            {STATUS_TEXT[trust.status] ?? "Unknown"}
          </div>
          <div className="mt-1 text-xs tabular-nums text-muted-foreground">
            {plural(finite(trust.total_actions), ctx, { one: "{n} action", other: "{n} actions" })} ·{" "}
            {plural(finite(trust.overrides), ctx, { one: "{n} override", other: "{n} overrides" })}
          </div>
        </div>

        <div className="w-[120px] shrink-0">
          <div
            role="progressbar"
            aria-label="Trust score"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(percentage)}
            aria-valuetext={formatPercent(percentage, ctx)}
            className="h-2 overflow-hidden rounded-full bg-surface-3"
          >
            <div
              className={cn("h-full transition-[width] duration-base ease-console motion-reduce:transition-none", colors.bar)}
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
