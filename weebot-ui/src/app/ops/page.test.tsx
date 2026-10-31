import { act, fireEvent, render, screen } from "@testing-library/react";
import { CostChart } from "@/components/dashboard/CostChart";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket, type FakeWebSocketControl } from "../../../tests/harness/fake-transport";
import OpsPage from "./page";

vi.mock("@/components/plan/LazyPlanVisualizer", () => ({
  LazyPlanVisualizer: ({ title }: { title: string }) => <div data-testid="plan">{title}</div>,
}));

let sockets: FakeWebSocketControl;

beforeEach(() => {
  vi.useFakeTimers();
  sockets = installFakeWebSocket();
  Element.prototype.scrollIntoView = vi.fn();
  // Node 24 shadows jsdom's localStorage with an unusable stub unless --localstorage-file is set.
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {} });
  // The backend is down: every REST call fails, so only the live socket is under test.
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("down"))));
});
afterEach(() => {
  sockets.restore();
  vi.useRealTimers();
});

async function openLiveTab() {
  render(<OpsPage />);
  await act(async () => {
    fireEvent.click(screen.getByRole("tab", { name: "Live Events" }));
  });
}

describe("/ops live events caption reflects the socket (W5 D3)", () => {
  it("does not claim a connection before the socket opens", async () => {
    await openLiveTab();
    expect(screen.queryByText("WebSocket connected")).toBeNull();
  });

  it("says connected once the socket opens, and not after it drops", async () => {
    await openLiveTab();
    act(() => sockets.last.accept());
    expect(screen.getByText("WebSocket connected")).toBeTruthy();

    act(() => sockets.last.serverClose());
    expect(screen.queryByText("WebSocket connected")).toBeNull();
  });

  it("opens a replacement socket after a drop, and none after unmount", async () => {
    const { unmount } = render(<OpsPage />);
    act(() => sockets.last.accept());
    act(() => sockets.last.serverClose());
    expect(sockets.sockets).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(sockets.sockets).toHaveLength(2);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(sockets.sockets).toHaveLength(2);
  });

  it("still lists frames that arrive (no regression)", async () => {
    await openLiveTab();
    act(() => sockets.last.accept());
    act(() => sockets.last.emit({ type: "ping_evt", timestamp: "2026-10-31T10:11:12Z" }));
    expect(screen.getByText("ping_evt")).toBeTruthy();
  });
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
/** A backend that answers `routes` (URL suffix -> body) and 500s everything else. */
const backend = (routes: Record<string, () => Response>) =>
  vi.fn(async (url: string) => {
    const hit = Object.keys(routes).find((suffix) => String(url).endsWith(suffix));
    return hit ? routes[hit]() : json({ detail: "boom" }, 500);
  });
const plan = (id: string) => ({
  ok: true,
  data: { session_id: id, plan: { status: "x", nodes: [{ id: "1", label: "step", status: "done" }], edges: [] } },
});

async function loadPlan(id: string) {
  fireEvent.change(screen.getByPlaceholderText(/Enter session ID/), { target: { value: id } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Load" }));
    await vi.advanceTimersByTimeAsync(0);
  });
}

describe("/ops Plan Visualization tab (W5 R6)", () => {
  async function openPlanTab() {
    render(<OpsPage />);
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Plan Visualization" }));
    });
  }

  it("CLEARED: a 200 with ok:false cannot happen, the backend answers failures with an HTTP error", async () => {
    // ops_router.get_plan_visualization returns {"ok": True, ...} or raises HTTPException, so the
    // `if (result.ok)` without an else is unreachable on its false side; an error is surfaced.
    vi.stubGlobal("fetch", backend({ "/plan-viz": () => json({ detail: "Session not found" }, 404) }));
    await openPlanTab();
    await loadPlan("nope");
    expect(screen.getByText("Session not found")).toBeTruthy();
  });

  it.fails("KNOWN DEFECT (budget): the title names the loaded session, not the text being typed", async () => {
    vi.stubGlobal("fetch", backend({ "/sessions/a/plan-viz": () => json(plan("a")) }));
    await openPlanTab();
    await loadPlan("a");
    expect(screen.getByTestId("plan").textContent).toBe("Plan for a");
    fireEvent.change(screen.getByPlaceholderText(/Enter session ID/), { target: { value: "ab" } });
    expect(screen.getByTestId("plan").textContent).toBe("Plan for a");
  });

  it.fails("KNOWN DEFECT (budget): a failed load does not leave the previous session's plan on screen", async () => {
    vi.stubGlobal(
      "fetch",
      backend({
        "/sessions/a/plan-viz": () => json(plan("a")),
        "/sessions/b/plan-viz": () => json({ detail: "Session not found" }, 404),
      })
    );
    await openPlanTab();
    await loadPlan("a");
    await loadPlan("b");
    expect(screen.queryByTestId("plan")).toBeNull();
  });
});

describe("/ops overview with the backend down (W5 R4)", () => {
  it.fails("KNOWN DEFECT (budget): metrics are not presented as measured zeros", async () => {
    render(<OpsPage />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // fetch rejects for every call: the health card says so, the metrics card shows 0% CPU, 0 MB.
    expect(screen.queryAllByText("0%", { selector: "div.text-2xl" })).toHaveLength(0);
  });

  it.fails("KNOWN DEFECT (budget): a metrics failure does not discard a healthy /health answer", async () => {
    vi.stubGlobal("fetch", backend({ "/health": () => json({ status: "healthy", components: [], timestamp: "t" }) }));
    render(<OpsPage />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.queryByText("Failed to load health status")).toBeNull();
  });

  it("polls health and metrics every 10 s and stops on unmount (loop is bounded)", async () => {
    const fetchStub = vi.fn(() => Promise.reject(new TypeError("down")));
    vi.stubGlobal("fetch", fetchStub);
    const { unmount } = render(<OpsPage />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const first = fetchStub.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetchStub.mock.calls.length).toBe(first * 2);
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(fetchStub.mock.calls.length).toBe(first * 2);
  });
});

describe("/ops health vocabulary (W5 D4b)", () => {
  it("CODE-INNOCENT at the top level: every status /health emits for the overall field has a colour", async () => {
    const body = (status: string) => ({ status, components: [], timestamp: "t" });
    for (const [status, cls] of [
      ["healthy", "bg-status-live"],
      ["degraded", "bg-status-waiting"],
      ["unhealthy", "bg-status-error"],
    ] as const) {
      vi.stubGlobal("fetch", backend({ "/health": () => json(body(status)), "/dashboard/metrics": () => json({}) }));
      const { container, unmount } = render(<OpsPage />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(container.querySelector(`div.rounded-full.${cls}`)).not.toBeNull();
      unmount();
    }
  });
});

describe("CostChart edge inputs (W5 R5)", () => {
  it("CLEARED: one row, zero totals and no models render without NaN or Infinity", () => {
    const { container } = render(
      <CostChart dailyCosts={[{ date: "2026-10-31", cost: 0, tokens: 0 }]} modelUsage={[]} totalCost={0} totalTokens={0} />
    );
    expect(container.textContent).not.toMatch(/NaN|Infinity/);
    expect(container.textContent).toContain("$0.0000");
  });
});
