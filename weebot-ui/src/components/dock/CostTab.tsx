"use client";

/**
 * CostTab — cascade cost summary. Not session-scoped (the backend's
 * /costs/summary endpoint reports process-wide cascade stats, not
 * per-session spend), shown here as the closest available signal for
 * "what is this running me."
 */

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, CostSummaryData } from "@/lib/api";

export function CostTab() {
  const [summary, setSummary] = useState<CostSummaryData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.ops
      .costSummary(24)
      .then((result) => {
        if (!cancelled && result.ok) setSummary(result.data);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center py-8">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!summary) {
    return <p className="p-4 text-xs text-muted-foreground">No cost data available.</p>;
  }

  // The API is intentionally treated as untrusted at this UI boundary: a
  // partially upgraded backend must show a useful empty value, never take
  // down the entire session workspace.
  const totalCost = Number.isFinite(summary.total_cost) ? summary.total_cost : 0;
  const totalTokens = Number.isFinite(summary.total_tokens) ? summary.total_tokens : 0;
  const calls = Number.isFinite(summary.calls) ? summary.calls : 0;
  const windowHours = Number.isFinite(summary.window_hours) ? summary.window_hours : 24;
  const byModel = summary.by_model && typeof summary.by_model === "object" ? summary.by_model : {};

  return (
    <div className="space-y-3 p-3 text-sm">
      <div className="flex justify-between">
        <span className="text-muted-foreground">Process cost ({windowHours}h)</span>
        <span className="font-mono font-medium">${totalCost.toFixed(4)}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Model calls</span>
        <span className="font-mono">{calls}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Tokens</span>
        <span className="font-mono">{totalTokens.toLocaleString()}</span>
      </div>
      <div className="border-t pt-2">
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">Models</p>
        {Object.entries(byModel).map(([model, stats]) => (
          <div key={model} className="flex justify-between text-xs">
            <span className="max-w-40 truncate" title={model}>{model}</span>
            <span className="font-mono text-muted-foreground">
              ${stats.cost.toFixed(4)} · {stats.calls} calls
            </span>
          </div>
        ))}
        {Object.keys(byModel).length === 0 && (
          <p className="text-xs text-muted-foreground">No model calls in this window.</p>
        )}
      </div>
    </div>
  );
}
