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

  return (
    <div className="space-y-3 p-3 text-sm">
      <div className="flex justify-between">
        <span className="text-muted-foreground">Total cost (24h)</span>
        <span className="font-mono font-medium">${summary.total_cost_usd.toFixed(4)}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Decisions</span>
        <span className="font-mono">{summary.total_decisions}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Avg latency</span>
        <span className="font-mono">{summary.avg_latency_ms.toFixed(0)}ms</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Cascade hit rate</span>
        <span className="font-mono">{(summary.cascade_hit_rate * 100).toFixed(1)}%</span>
      </div>
      <div className="border-t pt-2">
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">Tiers</p>
        {Object.entries(summary.tiers).map(([tier, stats]) => (
          <div key={tier} className="flex justify-between text-xs">
            <span className="capitalize">{tier}</span>
            <span className="font-mono text-muted-foreground">
              {stats.success} ok · {stats.failure} fail
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
