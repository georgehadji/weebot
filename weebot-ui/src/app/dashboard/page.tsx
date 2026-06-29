"use client";

import { useEffect, useRef, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CostChart } from "@/components/dashboard/CostChart";
import { MetricsPanel } from "@/components/dashboard/MetricsPanel";
import { PlanVisualizer } from "@/components/plan/PlanVisualizer";
import { CodeEditor } from "@/components/code/CodeEditor";
import { api, ActiveSession } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";

interface DashboardData {
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
  timestamp: string;
  type: string;
  raw: string;
}

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";

export default function DashboardPage() {
  const [health, setHealth] = useState<{ status: string; components: { name: string; status: string }[]; timestamp: string } | null>(null);
  const [metrics, setMetrics] = useState<DashboardData | null>(null);
  const [activeSessions, setActiveSessions] = useState<ActiveSession[]>([]);
  const [loading, setLoading] = useState(true);

  // Live log stream via global WebSocket
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ws = new WebSocket(WS_BASE);
    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        const entry: LogEntry = {
          timestamp: data.timestamp || new Date().toISOString(),
          type: data.type || "event",
          raw: JSON.stringify(data),
        };
        setLogs((prev) => [...prev.slice(-199), entry]);
      } catch {
        // ignore non-JSON frames
      }
    };
    return () => ws.close();
  }, []);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [healthData, metricsData] = await Promise.all([
          api.health.check(),
          api.dashboard.metrics(),
        ]);
        setHealth(healthData);
        setMetrics(metricsData);
      } catch {
        // backend may not be running
      } finally {
        setLoading(false);
      }
    };

    const fetchActiveSessions = async () => {
      try {
        const result = await api.ops.activeSessions(20);
        if (result.ok) setActiveSessions(result.data);
      } catch {
        // ignore
      }
    };

    fetchData();
    fetchActiveSessions();

    const interval = setInterval(() => {
      fetchData();
      fetchActiveSessions();
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  const realMetrics = metrics
    ? {
        activeSessions: metrics.active_sessions,
        totalSessions: metrics.total_sessions,
        avgResponseTime: metrics.avg_response_time,
        cpuUsage: metrics.cpu_usage,
        memoryUsage: metrics.memory_usage,
        dbSize: metrics.db_size,
        requestsPerMinute: metrics.requests_per_minute,
      }
    : {
        activeSessions: 0,
        totalSessions: 0,
        avgResponseTime: 0,
        cpuUsage: 0,
        memoryUsage: 0,
        dbSize: "0 MB",
        requestsPerMinute: 0,
      };

  const dailyCosts = metrics?.daily_costs || [];
  const modelUsage = metrics?.model_usage || [];
  const totalCost = metrics?.total_cost || 0;
  const totalTokens = metrics?.total_tokens || 0;

  return (
    <div className="container mx-auto py-8 px-4">
      <h1 className="text-3xl font-bold mb-6">Dashboard</h1>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="active">
            Active Sessions
            {activeSessions.length > 0 && (
              <Badge className="ml-2 h-5 px-1.5 text-xs" variant="default">
                {activeSessions.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="costs">Cost Tracking</TabsTrigger>
          <TabsTrigger value="plan">Plan Visualization</TabsTrigger>
          <TabsTrigger value="code">Code Editor</TabsTrigger>
          <TabsTrigger value="logs">Live Events</TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>System Metrics</CardTitle>
            </CardHeader>
            <CardContent>
              <MetricsPanel metrics={realMetrics} />
            </CardContent>
          </Card>

          <div className="grid md:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Health Status</CardTitle>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <p className="text-muted-foreground">Loading...</p>
                ) : health ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <div
                        className={`w-3 h-3 rounded-full ${
                          health.status === "healthy"
                            ? "bg-green-500"
                            : health.status === "degraded"
                            ? "bg-yellow-500"
                            : "bg-red-500"
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
                          <span
                            className={
                              c.status === "healthy"
                                ? "text-green-600"
                                : c.status === "degraded"
                                ? "text-yellow-600"
                                : "text-red-600"
                            }
                          >
                            {c.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-red-500">Failed to load health status</p>
                )}
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
                    <span className="font-bold text-lg">${totalCost.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Total Tokens (7 days)</span>
                    <span className="font-bold text-lg" suppressHydrationWarning>
                      {totalTokens.toLocaleString()}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Active Models</span>
                    <span className="font-bold text-lg">{modelUsage.length}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Completed Sessions</span>
                    <span className="font-bold text-lg">{metrics?.completed_sessions || 0}</span>
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
              {activeSessions.length === 0 ? (
                <p className="text-muted-foreground text-center py-8">
                  No sessions currently running.
                </p>
              ) : (
                <div className="space-y-3">
                  {activeSessions.map((s) => (
                    <div
                      key={s.id}
                      className="flex items-center justify-between p-3 rounded-lg border bg-card"
                    >
                      <div>
                        <p className="font-mono text-sm font-medium">{s.id}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {s.steps_completed}/{s.step_count} steps · {s.tool_calls} tool calls ·{" "}
                          {s.event_count} events
                        </p>
                      </div>
                      <Badge
                        variant={s.status === "running" ? "default" : "secondary"}
                      >
                        {s.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
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

        {/* Code Editor Tab */}
        <TabsContent value="code">
          <Card>
            <CardHeader>
              <CardTitle>Code Editor</CardTitle>
            </CardHeader>
            <CardContent>
              <CodeEditor
                initialValue={`# Welcome to Weebot Code Editor\n# Write and execute code here\n\ndef fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n - 1) + fibonacci(n - 2)\n\nfor i in range(10):\n    print(f"F({i}) = {fibonacci(i)}")`}
                language="python"
                height="500px"
                onExecute={async (code) => {
                  alert("Code execution:\n\n" + code.slice(0, 200) + (code.length > 200 ? "..." : ""));
                }}
                onSave={async () => {
                  alert("Code saved!");
                }}
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* Live Events Tab */}
        <TabsContent value="logs">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Live Event Stream</CardTitle>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                  <span className="text-xs text-muted-foreground">WebSocket connected</span>
                  {logs.length > 0 && (
                    <button
                      onClick={() => setLogs([])}
                      className="text-xs text-muted-foreground hover:text-foreground underline"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[500px]">
                <div className="font-mono text-xs space-y-0.5 bg-black text-green-400 p-4 rounded-lg min-h-[460px]">
                  {logs.length === 0 ? (
                    <div className="text-gray-500">
                      Waiting for events… Start a session to see live output.
                    </div>
                  ) : (
                    logs.map((entry, i) => (
                      <div key={i} className="flex gap-2">
                        <span className="text-gray-500 shrink-0">
                          {entry.timestamp.slice(11, 19)}
                        </span>
                        <Badge
                          variant="outline"
                          className="text-[10px] h-4 px-1 shrink-0 border-green-800 text-green-500"
                        >
                          {entry.type}
                        </Badge>
                        <span className="truncate">{entry.raw}</span>
                      </div>
                    ))
                  )}
                  <div ref={logsEndRef} />
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function PlanVizTab() {
  const [sessionId, setSessionId] = useState("");
  const [planData, setPlanData] = useState<{
    nodes: { id: string; description: string; status: "pending" | "running" | "completed" | "error" }[];
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPlan = async () => {
    if (!sessionId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.ops.planViz(sessionId.trim());
      if (result.ok) {
        setPlanData({
          nodes: result.data.nodes.map((n) => ({
            id: n.id,
            description: n.label,
            status: (n.status as "pending" | "running" | "completed" | "error") || "pending",
          })),
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load plan");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Execution Plan</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <input
            className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            placeholder="Enter session ID to visualize its plan…"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fetchPlan()}
          />
          <button
            onClick={fetchPlan}
            disabled={!sessionId.trim() || loading}
            className="inline-flex items-center justify-center rounded-md text-sm font-medium h-9 px-4 py-2 bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Load"}
          </button>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        {planData ? (
          <PlanVisualizer steps={planData.nodes} title={`Plan for ${sessionId}`} />
        ) : (
          <p className="text-sm text-muted-foreground">
            Enter a session ID above to visualize its execution plan.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
