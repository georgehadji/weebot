"use client";

import { useEffect, useRef } from "react";
import { Activity, Clock, Cpu, Database } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useIntlContext } from "@/hooks/useIntlContext";
import { formatNumber, formatPercent } from "@/lib/format";
import { useAnnounce } from "@/providers/AnnouncerProvider";

interface Metrics {
  activeSessions: number;
  totalSessions: number;
  avgResponseTime: number;
  cpuUsage: number;
  memoryUsage: number;
  dbSize: string;
  requestsPerMinute: number;
}

interface MetricsPanelProps {
  metrics: Metrics;
}

/** Usage at or above this is "high". */
const HIGH_USAGE = 90;

/**
 * Announces when `value` crosses the high-usage line, in either direction. The polled values
 * themselves stay silent, and a panel that mounts already high says nothing.
 */
function useThresholdAnnouncement(label: string, value: number) {
  const announce = useAnnounce();
  const high = value >= HIGH_USAGE;
  const wasHigh = useRef(high);
  useEffect(() => {
    if (wasHigh.current !== high) {
      announce(high ? `${label} is high, ${formatPercent(value)}.` : `${label} is back to normal.`);
      wasHigh.current = high;
    }
  }, [high, label, value, announce]);
}

const ICON = "h-4 w-4 text-muted-foreground";
const VALUE = "text-2xl font-bold tabular-nums";

// The page wraps this panel in its own h2 card, so each metric is an h3.
const h3 = <h3 />;

export function MetricsPanel({ metrics }: MetricsPanelProps) {
  const ctx = useIntlContext();
  useThresholdAnnouncement("CPU usage", metrics.cpuUsage);
  useThresholdAnnouncement("Memory usage", metrics.memoryUsage);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle render={h3} className="text-sm font-medium">Active Sessions</CardTitle>
          <Activity className={ICON} aria-hidden="true" />
        </CardHeader>
        <CardContent>
          <div className={VALUE}>{formatNumber(metrics.activeSessions, ctx)}</div>
          <p className="text-xs text-muted-foreground tabular-nums">
            of {formatNumber(metrics.totalSessions, ctx)} total
          </p>
          <Progress
            value={(metrics.activeSessions / Math.max(metrics.totalSessions, 1)) * 100}
            aria-label="Active sessions as a share of all sessions"
            className="mt-2"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle render={h3} className="text-sm font-medium">Avg Response Time</CardTitle>
          <Clock className={ICON} aria-hidden="true" />
        </CardHeader>
        <CardContent>
          <div className={VALUE}>
            {formatNumber(metrics.avgResponseTime, ctx, {
              style: "unit",
              unit: "millisecond",
              unitDisplay: "narrow",
              maximumFractionDigits: 0,
            })}
          </div>
          <p className="text-xs text-muted-foreground">
            Last hour average
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle render={h3} className="text-sm font-medium">CPU Usage</CardTitle>
          <Cpu className={ICON} aria-hidden="true" />
        </CardHeader>
        <CardContent>
          <div className={VALUE}>{formatPercent(metrics.cpuUsage, ctx)}</div>
          <Progress value={metrics.cpuUsage} aria-label="CPU usage" className="mt-2" />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle render={h3} className="text-sm font-medium">Memory Usage</CardTitle>
          <Database className={ICON} aria-hidden="true" />
        </CardHeader>
        <CardContent>
          <div className={VALUE}>{formatPercent(metrics.memoryUsage, ctx)}</div>
          <Progress value={metrics.memoryUsage} aria-label="Memory usage" className="mt-2" />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle render={h3} className="text-sm font-medium">Database Size</CardTitle>
          <Database className={ICON} aria-hidden="true" />
        </CardHeader>
        <CardContent>
          <div className={VALUE}>{metrics.dbSize}</div>
          <p className="text-xs text-muted-foreground">
            SQLite storage
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle render={h3} className="text-sm font-medium">Requests/Min</CardTitle>
          <Activity className={ICON} aria-hidden="true" />
        </CardHeader>
        <CardContent>
          <div className={VALUE}>{formatNumber(metrics.requestsPerMinute, ctx)}</div>
          <p className="text-xs text-muted-foreground">
            Average over last 5 min
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
