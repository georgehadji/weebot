import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RecentAction, TrustScore } from "@/hooks/useBehavior";

// BehaviorPanel merges two hooks; the merge is what is under test, so the hooks are stubbed.
const hooks = vi.hoisted(() => ({
  ws: {} as Record<string, unknown>,
  rest: {} as Record<string, unknown>,
}));
vi.mock("@/hooks/useBehavior", async (orig) => ({
  ...(await orig<typeof import("@/hooks/useBehavior")>()),
  useBehavior: () => hooks.ws,
  useBehaviorREST: () => hooks.rest,
}));

import { BehaviorPanel } from "./BehaviorPanel";
import { RecentActions } from "./RecentActions";

const real = await vi.importActual<typeof import("@/hooks/useBehavior")>("@/hooks/useBehavior");

const fullTrust: TrustScore = {
  score_percentage: 95,
  score: 0.95,
  total_actions: 40,
  overrides: 2,
  last_updated: "2026-10-31T10:00:00Z",
  status: "trusted",
};
// What /api/behavior/ws really sends on connect: no status, no score_percentage.
const wsConnectTrust = { score: 95, total_actions: 40, overrides: 2 } as unknown as TrustScore;

const act1: RecentAction = { timestamp: "t1", action: "created", path: "a/b/old.txt", is_override: false };
const act2: RecentAction = { timestamp: "t2", action: "modified", path: "a/b/new.txt", is_override: true };

function setHooks(ws: Record<string, unknown>, rest: Record<string, unknown>) {
  hooks.ws = { events: [], trustScore: null, isConnected: false, recentActions: [], ...ws };
  hooks.rest = {
    trustScore: null,
    recentActions: [],
    isLoading: false,
    isUnavailable: false,
    refreshAll: vi.fn(),
    ...rest,
  };
}

describe("BehaviorPanel prefers complete polled data over the socket's snapshot (W5 B1)", () => {
  it("shows the real trust status, not 'Unknown', while the socket is connected", () => {
    setHooks({ isConnected: true, trustScore: wsConnectTrust }, { trustScore: fullTrust });
    render(<BehaviorPanel />);
    expect(screen.getByText("Trusted")).toBeTruthy();
    expect(screen.queryByText("Unknown")).toBeNull();
  });

  it("shows an override marked after the socket's one-off snapshot (REST list wins)", () => {
    setHooks({ isConnected: true, recentActions: [act1] }, { recentActions: [act1, act2] });
    render(<BehaviorPanel />);
    expect(screen.getByText("b/new.txt")).toBeTruthy();
  });

  it("falls back to the socket's data when REST has none (boundary: REST unavailable)", () => {
    setHooks(
      { isConnected: true, trustScore: wsConnectTrust, recentActions: [act1] },
      { isUnavailable: true }
    );
    render(<BehaviorPanel />);
    expect(screen.getByText("b/old.txt")).toBeTruthy();
    expect(screen.getByText("Live")).toBeTruthy();
  });

  it("uses REST data when the socket is down (no regression)", () => {
    setHooks({}, { trustScore: fullTrust, recentActions: [act2] });
    render(<BehaviorPanel />);
    expect(screen.getByText("Trusted")).toBeTruthy();
    expect(screen.getByText("b/new.txt")).toBeTruthy();
  });
});

describe("useBehaviorREST reads the shape /api/behavior/recent returns (W5 B2)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("maps the response's event_type onto RecentAction.action", async () => {
    const rows = [
      { timestamp: "t1", event_type: "deleted", path: "x/y/z.txt", session_id: "s", agent_version: "1", initiated: "autonomous", is_override: false },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        new Response(JSON.stringify(String(url).includes("/recent") ? rows : fullTrust), { status: 200 })
      )
    );
    const { result } = renderHook(() => real.useBehaviorREST());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.recentActions[0].action).toBe("deleted");
    expect(result.current.recentActions[0].path).toBe("x/y/z.txt");
  });

  it("an empty list stays empty (boundary)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
    const { result } = renderHook(() => real.useBehaviorREST());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.recentActions).toEqual([]);
  });
});

describe("RecentActions override failures are shown (W5 B3, decision D-BEH)", () => {
  afterEach(() => vi.unstubAllGlobals());

  async function submitOverride(response: Response | Error) {
    const fetchStub = vi.fn(async () => {
      if (response instanceof Error) throw response;
      return response;
    });
    vi.stubGlobal("fetch", fetchStub);
    const onRefresh = vi.fn();
    render(<RecentActions actions={[act1]} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByText("b/old.txt"));
    fireEvent.change(screen.getByPlaceholderText("Why was this action incorrect?"), {
      target: { value: "wrong file" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Mark Override" }));
    });
    return { fetchStub, onRefresh };
  }

  it("a 404 keeps the dialog open and says why", async () => {
    await submitOverride(new Response(JSON.stringify({ detail: "Action not found: t1" }), { status: 404 }));
    expect(screen.getByRole("alert").textContent).toContain("Action not found");
    expect(screen.getByText("Mark as Override")).toBeTruthy();
  });

  it("an unreachable backend is reported too (boundary)", async () => {
    await submitOverride(new TypeError("fetch failed"));
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("goes through the configured API base, same as every other behavior call", async () => {
    const { fetchStub } = await submitOverride(new Response("{}", { status: 200 }));
    expect(String((fetchStub.mock.calls as unknown[][])[0][0])).toBe("/api/behavior/override");
  });

  it("success closes the dialog and refreshes (no regression)", async () => {
    const { onRefresh } = await submitOverride(new Response("{}", { status: 200 }));
    expect(screen.queryByText("Mark as Override")).toBeNull();
    expect(onRefresh).toHaveBeenCalled();
  });
});
