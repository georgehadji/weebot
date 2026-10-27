import { AgentEvent, ModelInfo, RoleModel, Session } from "@/types/events";

/** Same-origin API base by default; respects an explicitly configured backend. */
export function getApiBase(): string {
  if (typeof window === "undefined") return "/api";
  try {
    const configured = localStorage.getItem("weebot_backend_url")?.trim();
    if (!configured) return "/api";
    return `${configured.replace(/\/$/, "")}/api`;
  } catch {
    return "/api";
  }
}

/** Read API key from sessionStorage (set via ConnectionStatus component). */
function _getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem("weebot_api_key");
  } catch {
    return null;
  }
}

/** The X-API-Key header for calls made outside fetchApi (empty when no key is set). */
export function authHeaders(): Record<string, string> {
  const apiKey = _getApiKey();
  return apiKey ? { "X-API-Key": apiKey } : {};
}

/**
 * Open a WebSocket to the backend. The API key travels in the Sec-WebSocket-Protocol header
 * as `bearer.<key>`, next to the marker `weebot.v1` the server answers with. It used to be
 * `?token=`, which uvicorn writes to its access log.
 */
export function openSocket(url: string, apiKey: string | null = _getApiKey()): WebSocket {
  return apiKey ? new WebSocket(url, ["weebot.v1", `bearer.${apiKey}`]) : new WebSocket(url);
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
    const response = await fetch(`${getApiBase()}${path}`, {
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
  session_id: string;
  plan: {
    status: string;
    nodes: { id: string; label: string; status: string; result?: string }[];
    edges: { from: string; to: string }[];
  } | null;
}

export interface CostSummaryData {
  /** Mirrors EventStorePort.get_cost_window() exactly. */
  total_cost: number;
  total_tokens: number;
  calls: number;
  by_model: Record<string, { cost: number; tokens: number; calls: number }>;
  window_hours: number;
}

export interface ActiveSession {
  session_id: string;
  status: string;
  step_count: number;
  steps_completed: number;
  tool_calls: number;
  elapsed_events: number;
}

export interface ActiveSessionsData {
  sessions: ActiveSession[];
  total: number;
  limit: number;
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

    events: (id: string) => fetchApi<AgentEvent[]>(`/sessions/${id}/events`),

    delete: (id: string) => fetchApi<void>(`/sessions/${id}`, { method: "DELETE" }),

    cancel: (id: string) => fetchApi<Session>(`/sessions/${id}/cancel`, { method: "POST" }),

    run: (id: string) => fetchApi<Session>(`/sessions/${id}/run`, { method: "POST" }),

    resume: (id: string, answer: string) =>
      fetchApi<Session>(`/sessions/${id}/resume`, {
        method: "POST",
        body: JSON.stringify({ answer }),
      }),

    /**
     * Single entry point for the composer — the backend resolves
     * start/resume/steer/chat from the session's current status
     * (see application/use_cases/dispatch_session_input.py).
     */
    input: (id: string, text: string, opts?: { clientMsgId?: string; model?: string }) =>
      fetchApi<{ verb: string; session: Session }>(`/sessions/${id}/input`, {
        method: "POST",
        body: JSON.stringify({
          text,
          client_msg_id: opts?.clientMsgId,
          model: opts?.model,
        }),
      }),
  },

  models: {
    list: () => fetchApi<ModelInfo[]>("/models"),
    available: () => fetchApi<string[]>("/models/available"),
    roles: () => fetchApi<RoleModel[]>("/models/roles"),
    setRole: (role: string, model: string) =>
      fetchApi<RoleModel>(`/models/roles/${encodeURIComponent(role)}`, {
        method: "PUT",
        body: JSON.stringify({ model }),
      }),
    resetRole: (role: string) =>
      fetchApi<RoleModel>(`/models/roles/${encodeURIComponent(role)}`, { method: "DELETE" }),
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
      fetchApi<{ ok: boolean; data: ActiveSessionsData }>(
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
