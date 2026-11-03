"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { StateView } from "@/components/common/StateView";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useIntlContext } from "@/hooks/useIntlContext";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { formatCurrency, formatDate, formatNumber, formatPercent, plural } from "@/lib/format";

interface CostData {
  date: string;
  cost: number;
  tokens: number;
}

interface ModelUsage {
  name: string;
  cost: number;
  usage: number;
}

interface CostChartProps {
  dailyCosts: CostData[];
  modelUsage: ModelUsage[];
  totalCost: number;
  totalTokens: number;
}

// Series colours are theme tokens (globals.css); Recharts passes them to SVG, which resolves var().
const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
const seriesColor = (index: number) => SERIES[index % SERIES.length];

const AXIS = { stroke: "hsl(var(--muted-foreground))", tick: { fill: "hsl(var(--muted-foreground))", fontSize: 12 } };
const TOOLTIP_STYLE = {
  background: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  borderRadius: 8,
  color: "hsl(var(--popover-foreground))",
};

// The page wraps this chart in its own h2 card, so each card here is an h3.
const h3 = <h3 />;

/**
 * A chart plus its text alternative. The graphic is `role="img"` with a summary label (its
 * children are invisible to assistive technology), so the same numbers go in an `sr-only` table
 * beside it, not inside it.
 */
function ChartFigure({
  label,
  caption,
  head,
  rows,
  children,
}: {
  label: string;
  caption: string;
  head: string[];
  rows: string[][];
  children: React.ReactNode;
}) {
  return (
    <figure className="m-0 min-w-0">
      <div role="img" aria-label={label}>
        {children}
      </div>
      <table className="sr-only">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]}>
              {row.map((cell, i) => (
                <td key={i}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

export function CostChart({
  dailyCosts,
  modelUsage,
  totalCost,
  totalTokens,
}: CostChartProps) {
  const ctx = useIntlContext();
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const money = (n: number) => formatCurrency(n, ctx, { precision: 4 });
  // "2026-10-30" is a calendar day, not an instant: in UTC it cannot shift to the day before.
  const day = (date: string) => formatDate(date, { ...ctx, timeZone: "UTC" }) ?? date;

  const days = dailyCosts.length;
  const peak = dailyCosts.reduce<CostData | null>((top, d) => (top === null || d.cost > top.cost ? d : top), null);
  const dailyLabel = peak
    ? `Daily cost bar chart over ${plural(days, ctx, { one: "{n} day", other: "{n} days" })}. Highest: ${money(peak.cost)} on ${day(peak.date)}.`
    : "Daily cost bar chart, no data.";

  const modelsTotal = modelUsage.reduce((sum, m) => sum + m.cost, 0);
  const share = (cost: number) => formatPercent(modelsTotal > 0 ? (cost / modelsTotal) * 100 : 0, ctx);
  const pieLabel = `Cost by model pie chart: ${modelUsage.map((m) => `${m.name} ${share(m.cost)}`).join(", ")}.`;

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle render={h3} className="text-sm font-medium text-muted-foreground">
              Total Cost
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tabular-nums">{money(totalCost)}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle render={h3} className="text-sm font-medium text-muted-foreground">
              Total Tokens
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tabular-nums">{formatNumber(totalTokens, ctx)}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle render={h3} className="text-sm font-medium text-muted-foreground">
              Avg Cost/1K Tokens
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tabular-nums">
              {money(totalTokens > 0 ? (totalCost / totalTokens) * 1000 : 0)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Daily Cost Chart */}
      <Card>
        <CardHeader>
          <CardTitle render={h3}>
            Daily Cost ({plural(days, ctx, { one: "Latest Day", other: "Last {n} Days" })})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartFigure
            label={dailyLabel}
            caption="Daily cost"
            head={["Date", "Cost", "Tokens"]}
            rows={dailyCosts.map((d) => [day(d.date), money(d.cost), formatNumber(d.tokens, ctx)])}
          >
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={dailyCosts}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="date" tickFormatter={day} {...AXIS} />
                <YAxis width={76} tickFormatter={(v) => money(Number(v))} {...AXIS} />
                <Tooltip
                  formatter={(value) => [money(Number(value)), "Cost"]}
                  labelFormatter={(label) => day(String(label))}
                  contentStyle={TOOLTIP_STYLE}
                />
                <Bar dataKey="cost" fill={SERIES[0]} isAnimationActive={!reducedMotion} />
              </BarChart>
            </ResponsiveContainer>
          </ChartFigure>
        </CardContent>
      </Card>

      {/* Model Usage Pie Chart */}
      <Card>
        <CardHeader>
          <CardTitle render={h3}>Cost by Model</CardTitle>
        </CardHeader>
        <CardContent>
          <StateView
            state={{ status: "ready", data: modelUsage }}
            isEmpty={(models) => models.length === 0}
            empty={<p className="py-8 text-center text-sm text-muted-foreground">No model usage yet.</p>}
          >
            {(models) => (
              <div className="grid md:grid-cols-2 gap-4">
                <ChartFigure
                  label={pieLabel}
                  caption="Cost by model"
                  head={["Model", "Cost", "Share", "Calls"]}
                  rows={models.map((m) => [m.name, money(m.cost), share(m.cost), formatNumber(m.usage, ctx)])}
                >
                  <ResponsiveContainer width="100%" height={300}>
                    <PieChart>
                      <Pie
                        data={models}
                        cx="50%"
                        cy="50%"
                        labelLine={false}
                        label={({ name, percent }) => `${name}: ${formatPercent((percent ?? 0) * 100, ctx)}`}
                        outerRadius={80}
                        fill={SERIES[0]}
                        dataKey="cost"
                        isAnimationActive={!reducedMotion}
                      >
                        {models.map((m, index) => (
                          <Cell key={m.name} fill={seriesColor(index)} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value) => money(Number(value))} contentStyle={TOOLTIP_STYLE} />
                    </PieChart>
                  </ResponsiveContainer>
                </ChartFigure>

                <ul className="min-w-0 space-y-2">
                  {models.map((model, index) => (
                    <li
                      key={model.name}
                      className="flex items-center justify-between gap-3 rounded-lg bg-muted p-2"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          aria-hidden="true"
                          className="h-3 w-3 shrink-0 rounded-full"
                          style={{ backgroundColor: seriesColor(index) }}
                        />
                        <span className="truncate font-medium" title={model.name} translate="no">
                          {model.name}
                        </span>
                      </div>
                      <div className="shrink-0 text-right tabular-nums">
                        <div className="font-bold">
                          {money(model.cost)}{" "}
                          <span className="text-xs font-normal text-muted-foreground">({share(model.cost)})</span>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {plural(model.usage, ctx, { one: "{n} call", other: "{n} calls" })}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </StateView>
        </CardContent>
      </Card>
    </div>
  );
}
