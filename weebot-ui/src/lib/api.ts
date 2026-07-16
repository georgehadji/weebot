import { ModelInfo, Session } from "@/types/events";

const API_BASE = "/api";

/** Read API key from sessionStorage (set via ConnectionStatus component). */
function _getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem("weebot_api_key");
  } catch {
    return null;
  }
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const apiKey = _getApiKey();

  const mergedHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (apiKey) {
    mergedHeaders["X-API-Key"] = apiKey;
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...mergedHeaders,
        ...(options?.headers as Record<string, string> | undefined),
      },
    });

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}`;
      try {
        const error = await response.json();
        errorMessage = error.detail || error.error || errorMessage;
      } catch {
        errorMessage = response.statusText || errorMessage;
      }
      throw new Error(errorMessage);
    }

    return response.json();
  } catch (error) {
    if (error instanceof Error) {
      if (error.message.includes("fetch") || error.message.includes("connect")) {
        throw new Error(
          "Cannot connect to backend. Make sure the backend server is running:\n\npython -m weebot.interfaces.web.main"
        );
      }
      throw error;
    }
    throw new Error("Unknown error occurred");
  }
}

export interface PlanVizData {
  plan_status: string;
  nodes: { id: string; label: string; status: string; result?: string }[];
  edges: { source: string; target: string }[];
}

export interface CostSummaryData {
  total_decisions: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  cascade_hit_rate: number;
  tiers: Record<string, { success: number; failure: number; circuit_open: number }>;
}

export interface ActiveSession {
  id: string;
  status: string;
  step_count: number;
  steps_completed: number;
  tool_calls: number;
  event_count: number;
}

export const api = {
  sessions: {
    list: (params?: { user_id?: string; status?: string; limit?: string; offset?: string }) =>
      fetchApi<{ sessions: Session[]; total: number }>(
        `/sessions?${new URLSearchParams(params as Record<string, string>)}`
      ),

    create: (data: {
      prompt: string;
      user_id?: string;
      agent_id?: string;
      model?: string;
      session_id?: string;
    }) => fetchApi<Session>("/sessions", { method: "POST", body: JSON.stringify(data) }),

    get: (id: string) => fetchApi<Session>(`/sessions/${id}`),

    delete: (id: string) => fetchApi<void>(`/sessions/${id}`, { method: "DELETE" }),

    cancel: (id: string) => fetchApi<Session>(`/sessions/${id}/cancel`, { method: "POST" }),

    run: (id: string) => fetchApi<Session>(`/sessions/${id}/run`, { method: "POST" }),

    resume: (id: string, answer: string) =>
      fetchApi<Session>(`/sessions/${id}/resume`, {
        method: "POST",
        body: JSON.stringify({ answer }),
      }),
  },

  models: {
    list: () => fetchApi<ModelInfo[]>("/models"),
    available: () => fetchApi<string[]>("/models/available"),
  },

  health: {
    check: () =>
      fetchApi<{ status: string; components: { name: string; status: string }[]; timestamp: string }>(
        "/health"
      ),
    ready: () => fetchApi<{ ready: boolean }>("/health/ready"),
    live: () => fetchApi<{ alive: boolean }>("/health/live"),
  },

  dashboard: {
    metrics: () =>
      fetchApi<{
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
      }>("/dashboard/metrics"),
  },

  ops: {
    activeSessions: (limit?: number) =>
      fetchApi<{ ok: boolean; data: ActiveSession[] }>(
        `/sessions/active${limit ? `?limit=${limit}` : ""}`
      ),

    planViz: (sessionId: string) =>
      fetchApi<{ ok: boolean; data: PlanVizData }>(`/sessions/${sessionId}/plan-viz`),

    costSummary: (windowHours?: number) =>
      fetchApi<{ ok: boolean; data: CostSummaryData }>(
        `/costs/summary${windowHours ? `?window_hours=${windowHours}` : ""}`
      ),
  },
};
