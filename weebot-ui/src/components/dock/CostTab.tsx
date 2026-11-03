"use client";

/**
 * CostTab — cascade cost summary. Not session-scoped (the backend's
 * /costs/summary endpoint reports process-wide cascade stats, not
 * per-session spend), shown here as the closest available signal for
 * "what is this running me."
 */

import { StateView } from "@/components/common/StateView";
import { useIntlContext } from "@/hooks/useIntlContext";
import { useRemote } from "@/hooks/useRemote";
import { formatCurrency, formatNumber, plural } from "@/lib/format";
import { api, CostSummaryData } from "@/lib/api";

// Module-level so useRemote gets a stable loader; `ok: false` means no summary, not a failure.
const loadSummary = () => api.ops.costSummary(24).then((result) => (result.ok ? result.data : null));

export function CostTab() {
  const { state, reload } = useRemote(loadSummary);
  return (
    <StateView
      state={state}
      loadingLabel="Loading costs"
      errorTitle="Couldn't load costs"
      onRetry={reload}
      isEmpty={(summary) => summary === null}
      empty={<p className="p-4 text-xs text-muted-foreground">No cost data available.</p>}
    >
      {(summary) => summary && <CostSummary summary={summary} />}
    </StateView>
  );
}

function CostSummary({ summary }: { summary: CostSummaryData }) {
  const ctx = useIntlContext();

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
        <span className="font-mono font-medium tabular-nums">{formatCurrency(totalCost, ctx, { precision: 4 })}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Model calls</span>
        <span className="font-mono tabular-nums">{formatNumber(calls, ctx)}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Tokens</span>
        <span className="font-mono tabular-nums">{formatNumber(totalTokens, ctx)}</span>
      </div>
      <div className="border-t pt-2">
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">Models</p>
        {Object.entries(byModel).map(([model, stats]) => (
          <div key={model} className="flex justify-between gap-2 text-xs">
            <span translate="no" className="min-w-0 truncate" title={model}>{model}</span>
            <span className="shrink-0 font-mono tabular-nums text-muted-foreground">
              {formatCurrency(stats.cost, ctx, { precision: 4 })} · {plural(stats.calls, ctx, { one: "{n} call", other: "{n} calls" })}
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
