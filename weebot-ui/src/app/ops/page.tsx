"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { MetricsPanel } from "@/components/dashboard/MetricsPanel";
import { LazyPlanVisualizer } from "@/components/plan/LazyPlanVisualizer";
import { api, openSocket } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ENDPOINTS } from "@/lib/endpoints";
import { formatCurrency, formatNumber, formatTime, plural } from "@/lib/format";
import { wsUrl } from "@/lib/settings";
import type { StepStatus } from "@/types/events";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useIntlContext } from "@/hooks/useIntlContext";
import { useRemote } from "@/hooks/useRemote";
import { useStickToBottom } from "@/hooks/useStickToBottom";
import { useUrlState } from "@/hooks/useUrlState";
import { remoteData } from "@/types/remote";
import { StateView } from "@/components/common/StateView";
import { useAnnounce } from "@/providers/AnnouncerProvider";
import { useToast } from "@/providers/ToastProvider";

interface OpsMetrics {
  total_sessions: number;
  active_sessions: number;
  completed_sessions: number;
  daily_costs: { date: string; cost: number; tokens: number }[];
  model_usage: { name: string; cost: number; usage: number }[];
  total_cost: number;
  total_tokens: number;
  cpu_usage: number;
  memory_usage: number;
  db_size: string;
  requests_per_minute: number;
  avg_response_time: number;
}

interface LogEntry {
  /** Assigned once, when the frame is ingested: a sliding window must not re-key its rows. */
  id: number;
  timestamp: string;
  type: string;
  raw: string;
}

const LOG_LIMIT = 200;
const UNDO_CLEAR_MS = 5000;
const TABS = ["overview", "active", "costs", "plan", "logs"] as const;

function getWsBase(): string {
  return wsUrl() || ENDPOINTS.ws;
}

const HEALTH_DOT: Record<string, string> = {
  healthy: "bg-status-live",
  degraded: "bg-status-waiting",
};
const HEALTH_TEXT: Record<string, string> = {
  healthy: "text-status-live-fg",
  degraded: "text-status-waiting-fg",
};

// recharts only matters once the cost tab is opened; keep it out of the first load.
type OpsHealth = { status: string; components: { name: string; status: string }[]; timestamp: string };
// Module-level so useRemote gets a stable loader; each source fails on its own.
const loadHealth = () => api.health.check() as Promise<OpsHealth>;
const loadMetrics = () => api.dashboard.metrics() as Promise<OpsMetrics>;
const loadActiveSessions = () =>
  api.ops.activeSessions(20).then((result) => {
    if (!result.ok) throw new Error("The server did not return the active sessions");
    return result.data.sessions;
  });

const CostChart = dynamic(() => import("@/components/dashboard/CostChart").then((m) => m.CostChart), {
  ssr: false,
  loading: () => (
    <div role="status">
      <Skeleton className="h-64 w-full" />
      <span className="sr-only">Loading chart…</span>
    </div>
  ),
});

export default function OpsPage() {
  return (
    <div className="container mx-auto py-8 px-4">
      <h2 className="text-3xl font-bold mb-6">Ops Console</h2>
      {/* The tab lives in the URL (useSearchParams), which needs a Suspense boundary. */}
      <Suspense
        fallback={
          <div role="status" className="text-sm text-muted-foreground">
            Loading…
          </div>
        }
      >
        <OpsConsole />
      </Suspense>
    </div>
  );
}

function OpsConsole() {
  const ctx = useIntlContext();
  const announce = useAnnounce();
  const { toast } = useToast();
  const [tabParam, setTab] = useUrlState("tab", "overview");
  const tab = TABS.find((t) => t === tabParam) ?? "overview";
  const { state: healthState, reload: reloadHealth } = useRemote(loadHealth, 10000);
  const { state: metricsState, reload: reloadMetrics } = useRemote(loadMetrics, 10000);
  const { state: activeState, reload: reloadActive } = useRemote(loadActiveSessions, 10000);
  const metrics = remoteData(metricsState);
  const activeSessions = remoteData(activeState) ?? [];

  // Live log stream via global WebSocket
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const nextLogId = useRef(0);
  const [wsLive, setWsLive] = useState(false);

  useEffect(() => {
    let disposed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ws: WebSocket;
    const connect = () => {
      ws = openSocket(getWsBase());
      ws.onopen = () => setWsLive(true);
      ws.onclose = () => {
        setWsLive(false);
        if (!disposed) retry = setTimeout(connect, 3000);
      };
      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          const entry: LogEntry = {
            id: nextLogId.current++,
            timestamp: data.timestamp || new Date().toISOString(),
            type: data.type || "event",
            raw: JSON.stringify(data),
          };
          setLogs((prev) => [...prev.slice(-(LOG_LIMIT - 1)), entry]);
        } catch {
          // ignore non-JSON frames
        }
      };
    };
    connect();
    return () => {
      disposed = true;
      clearTimeout(retry);
      ws.close();
    };
  }, []);

  // Announce the socket only when it changes, never on mount.
  const lastLive = useRef(wsLive);
  useEffect(() => {
    if (lastLive.current === wsLive) return;
    lastLive.current = wsLive;
    announce(wsLive ? "Live event stream connected" : "Live event stream disconnected. Reconnecting…");
  }, [wsLive, announce]);

  const clearLog = useCallback(() => {
    const cleared = logs;
    setLogs([]);
    toast({
      title: "Log cleared",
      durationMs: UNDO_CLEAR_MS,
      action: {
        label: "Undo",
        // Frames that arrived in the meantime stay, after the restored ones.
        onClick: () => setLogs((prev) => [...cleared, ...prev].slice(-LOG_LIMIT)),
      },
    });
  }, [logs, toast]);

  const dailyCosts = metrics?.daily_costs || [];
  const modelUsage = metrics?.model_usage || [];
  const totalCost = metrics?.total_cost || 0;
  const totalTokens = metrics?.total_tokens || 0;

  return (
    <Tabs value={tab} onValueChange={(next) => setTab(String(next))} className="space-y-6">
      <TabsList>
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="active">
          Active Sessions
          {activeSessions.length > 0 && (
            <Badge className="ml-2 h-5 px-1.5 text-xs tabular-nums" variant="default">
              {activeSessions.length}
            </Badge>
          )}
        </TabsTrigger>
        <TabsTrigger value="costs">Cost Tracking</TabsTrigger>
        <TabsTrigger value="plan">Plan Visualization</TabsTrigger>
        <TabsTrigger value="logs">Live Events</TabsTrigger>
      </TabsList>

      {/* Overview Tab */}
      <TabsContent value="overview" className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>System Metrics</CardTitle>
          </CardHeader>
          <CardContent>
            <StateView state={metricsState} errorTitle="Couldn't load metrics" loadingLabel="Loading metrics" onRetry={reloadMetrics}>
              {(m) => (
                <MetricsPanel
                  metrics={{
                    activeSessions: m.active_sessions,
                    totalSessions: m.total_sessions,
                    avgResponseTime: m.avg_response_time,
                    cpuUsage: m.cpu_usage,
                    memoryUsage: m.memory_usage,
                    dbSize: m.db_size,
                    requestsPerMinute: m.requests_per_minute,
                  }}
                />
              )}
            </StateView>
          </CardContent>
        </Card>

        <div className="grid md:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Health Status</CardTitle>
            </CardHeader>
            <CardContent>
              <StateView state={healthState} errorTitle="Failed to load health status" loadingLabel="Loading health" onRetry={reloadHealth}>
                {(health) => (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <div
                        className={`w-3 h-3 rounded-full ${
                          HEALTH_DOT[health.status] ?? "bg-status-error"
                        }`}
                      />
                      <span className="font-medium capitalize">{health.status}</span>
                    </div>
                    <div className="space-y-1">
                      {health.components?.map((c) => (
                        <div
                          key={c.name}
                          className="flex items-center justify-between text-sm p-2 rounded bg-muted"
                        >
                          <span>{c.name}</span>
                          <span className={HEALTH_TEXT[c.status] ?? "text-status-error-fg"}>
                            {c.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </StateView>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Quick Stats</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <span className="text-muted-foreground">Total Cost (7 days)</span>
                  <span className="font-bold text-lg tabular-nums">{formatCurrency(totalCost, ctx)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-muted-foreground">Total Tokens (7 days)</span>
                  <span className="font-bold text-lg tabular-nums">{formatNumber(totalTokens, ctx)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-muted-foreground">Active Models</span>
                  <span className="font-bold text-lg tabular-nums">{formatNumber(modelUsage.length, ctx)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-muted-foreground">Completed Sessions</span>
                  <span className="font-bold text-lg tabular-nums">
                    {formatNumber(metrics?.completed_sessions || 0, ctx)}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </TabsContent>

      {/* Active Sessions Tab */}
      <TabsContent value="active">
        <Card>
          <CardHeader>
            <CardTitle>Active Sessions</CardTitle>
          </CardHeader>
          <CardContent>
            <StateView
              state={activeState}
              errorTitle="Couldn't load active sessions"
              loadingLabel="Loading active sessions"
              onRetry={reloadActive}
              isEmpty={(sessions) => sessions.length === 0}
              empty={<p className="text-muted-foreground text-center py-8">No sessions currently running.</p>}
            >
              {(sessions) => (
                <ul className="space-y-3">
                  {sessions.map((s) => (
                    <li
                      key={s.session_id}
                      className="flex items-center justify-between gap-3 p-3 rounded-lg border bg-card"
                    >
                      <div className="min-w-0">
                        <Link
                          href={`/sessions/${encodeURIComponent(s.session_id)}`}
                          translate="no"
                          title={s.session_id}
                          className="block truncate font-mono text-sm font-medium hover:text-primary-text focus-ring rounded-sm"
                        >
                          {s.session_id}
                        </Link>
                        <p className="text-xs text-muted-foreground mt-0.5 tabular-nums">
                          {formatNumber(s.steps_completed, ctx)}/{formatNumber(s.step_count, ctx)}{" "}
                          {plural(s.step_count, ctx, { one: "step", other: "steps" })} ·{" "}
                          {plural(s.tool_calls, ctx, { one: "{n} tool call", other: "{n} tool calls" })} ·{" "}
                          {plural(s.elapsed_events, ctx, { one: "{n} event", other: "{n} events" })}
                        </p>
                      </div>
                      <Badge
                        className="shrink-0"
                        variant={s.status === "running" ? "default" : "secondary"}
                      >
                        {s.status}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </StateView>
          </CardContent>
        </Card>
      </TabsContent>

      {/* Cost Tracking Tab */}
      <TabsContent value="costs">
        <Card>
          <CardHeader>
            <CardTitle>Cost Analysis</CardTitle>
          </CardHeader>
          <CardContent>
            {dailyCosts.length > 0 ? (
              <CostChart
                dailyCosts={dailyCosts}
                modelUsage={modelUsage}
                totalCost={totalCost}
                totalTokens={totalTokens}
              />
            ) : (
              <p className="text-muted-foreground text-center py-8">
                No cost data available yet. Run some sessions to see metrics.
              </p>
            )}
          </CardContent>
        </Card>
      </TabsContent>

      {/* Plan Visualization Tab */}
      <TabsContent value="plan">
        <PlanVizTab />
      </TabsContent>

      {/* Live Events Tab */}
      <TabsContent value="logs">
        <LiveEventsCard logs={logs} wsLive={wsLive} onClear={clearLog} />
      </TabsContent>
    </Tabs>
  );
}

/** Its own component so the stick-to-bottom hook mounts with the log it observes. */
function LiveEventsCard({ logs, wsLive, onClear }: { logs: LogEntry[]; wsLive: boolean; onClear: () => void }) {
  const ctx = useIntlContext();
  const { viewportRef, sentinelRef } = useStickToBottom(logs.length);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Live Event Stream</CardTitle>
          <div className="flex items-center gap-2">
            <div
              aria-hidden="true"
              className={`w-2 h-2 rounded-full ${wsLive ? "bg-status-live motion-safe:animate-pulse" : "bg-status-idle"}`}
            />
            <span className="text-xs text-muted-foreground">
              {wsLive ? "WebSocket connected" : "Connecting…"}
            </span>
            {logs.length > 0 && (
              <Button variant="link" size="sm" onClick={onClear} className="h-auto px-1 py-0 text-xs text-muted-foreground">
                Clear Log
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[500px]" viewportRef={viewportRef}>
          <div
            role="log"
            aria-label="Live event log"
            className="font-mono text-xs space-y-0.5 bg-[hsl(var(--p-ink-1000))] text-[hsl(var(--p-cactus-300))] p-4 rounded-lg min-h-[460px]"
          >
            {logs.length === 0 ? (
              <div className="text-[hsl(var(--p-ink-500))]">
                Waiting for events… Start a session to see live output.
              </div>
            ) : (
              logs.map((entry) => (
                <div key={entry.id} className="flex gap-2">
                  <span className="text-[hsl(var(--p-ink-500))] shrink-0 tabular-nums">
                    {formatTime(entry.timestamp, ctx) ?? "--:--:--"}
                  </span>
                  <Badge
                    variant="outline"
                    className="text-xs h-4 px-1 shrink-0 border-[hsl(var(--p-olive-700))] text-[hsl(var(--p-cactus-300))]"
                  >
                    {entry.type}
                  </Badge>
                  <span className="truncate" title={entry.raw}>
                    {entry.raw}
                  </span>
                </div>
              ))
            )}
            <div ref={sentinelRef} aria-hidden="true" className="h-px" />
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

function PlanVizTab() {
  const [sessionId, setSessionId] = useState("");
  // The id travels with the plan: the title names what was loaded, not what is being typed.
  const [planData, setPlanData] = useState<{
    id: string;
    nodes: { id: string; description: string; status: StepStatus }[];
  } | null>(null);

  // Throws on failure, so the action's error state is the message; the guard drops a second
  // submit (Enter, or a double click) while one request is in flight.
  const { state, run, pending } = useAsyncAction(async () => {
    const id = sessionId.trim();
    if (!id) return;
    setPlanData(null); // a failed load must not leave the previous session's plan on screen
    const result = await api.ops.planViz(id);
    if (!result.ok) throw new Error("The server could not load that plan");
    const plan = result.data.plan;
    setPlanData({
      id,
      nodes: (plan?.nodes ?? []).map((n) => ({
        id: n.id,
        description: n.label,
        status: (n.status as StepStatus) || "pending",
      })),
    });
  });
  const error = state.status === "error" ? state.error : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Execution Plan</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          noValidate
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run();
          }}
        >
          <Label htmlFor="plan-session-id">Session ID</Label>
          <div className="flex gap-2">
            <Input
              id="plan-session-id"
              name="session-id"
              type="text"
              autoComplete="off"
              spellCheck={false}
              className="h-9 font-mono"
              placeholder="Enter a session ID to visualize its plan…"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "plan-session-error" : undefined}
            />
            <Button type="submit" loading={pending} disabled={!sessionId.trim()}>
              Load
            </Button>
          </div>
        </form>

        {error && (
          <p id="plan-session-error" role="alert" className="text-sm text-status-error-fg">
            {error}
          </p>
        )}

        {planData ? (
          <LazyPlanVisualizer steps={planData.nodes} title={`Plan for ${planData.id}`} />
        ) : (
          <p className="text-sm text-muted-foreground">
            Enter a session ID above to visualize its execution plan.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
