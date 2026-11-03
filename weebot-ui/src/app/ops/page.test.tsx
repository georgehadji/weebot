import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { CostChart } from "@/components/dashboard/CostChart";
import { AnnouncerProvider } from "@/providers/AnnouncerProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket, type FakeWebSocketControl } from "../../../tests/harness/fake-transport";
import OpsPage from "./page";

// The tab lives in the URL: a tiny router whose replace() updates what useSearchParams reads.
const nav = vi.hoisted(() => {
  const store = { search: "", subs: new Set<() => void>() };
  return {
    store,
    subscribe: (fn: () => void) => (store.subs.add(fn), () => store.subs.delete(fn)),
    replace: (url: string) => {
      store.search = url.split("?")[1] ?? "";
      store.subs.forEach((fn) => fn());
    },
  };
});
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useRouter: () => ({ replace: nav.replace }),
    usePathname: () => "/ops",
    useSearchParams: () =>
      new URLSearchParams(useSyncExternalStore(nav.subscribe, () => nav.store.search, () => nav.store.search)),
  };
});
vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => <a {...props}>{children}</a>,
}));

vi.mock("@/components/plan/LazyPlanVisualizer", () => ({
  LazyPlanVisualizer: ({ title }: { title: string }) => <div data-testid="plan">{title}</div>,
}));

let sockets: FakeWebSocketControl;

const renderOps = () =>
  render(
    <AnnouncerProvider>
      <ToastProvider>
        <OpsPage />
      </ToastProvider>
    </AnnouncerProvider>
  );

beforeEach(() => {
  vi.useFakeTimers();
  nav.store.search = "";
  window.history.replaceState({}, "", "/ops");
  sockets = installFakeWebSocket();
  // Node 24 shadows jsdom's localStorage with an unusable stub unless --localstorage-file is set.
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {} });
  // The backend is down: every REST call fails, so only the live socket is under test.
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("down"))));
});
afterEach(() => {
  sockets.restore();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function openLiveTab() {
  renderOps();
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
    const { unmount } = renderOps();
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
  fireEvent.change(screen.getByLabelText("Session ID"), { target: { value: id } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Load" }));
    await vi.advanceTimersByTimeAsync(0);
  });
}

describe("/ops Plan Visualization tab (W5 R6)", () => {
  async function openPlanTab() {
    renderOps();
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

  it("the title names the loaded session, not the text being typed", async () => {
    vi.stubGlobal("fetch", backend({ "/sessions/a/plan-viz": () => json(plan("a")) }));
    await openPlanTab();
    await loadPlan("a");
    expect(screen.getByTestId("plan").textContent).toBe("Plan for a");
    fireEvent.change(screen.getByLabelText("Session ID"), { target: { value: "ab" } });
    expect(screen.getByTestId("plan").textContent).toBe("Plan for a");
  });

  it("a failed load does not leave the previous session's plan on screen", async () => {
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
  it("metrics are not presented as measured zeros", async () => {
    renderOps();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // fetch rejects for every call: the health card says so, the metrics card shows 0% CPU, 0 MB.
    expect(screen.queryAllByText("0%", { selector: "div.text-2xl" })).toHaveLength(0);
  });

  it("a metrics failure does not discard a healthy /health answer", async () => {
    vi.stubGlobal("fetch", backend({ "/health": () => json({ status: "healthy", components: [], timestamp: "t" }) }));
    renderOps();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.queryByText("Failed to load health status")).toBeNull();
  });

  it("polls health and metrics every 10 s and stops on unmount (loop is bounded)", async () => {
    const fetchStub = vi.fn(() => Promise.reject(new TypeError("down")));
    vi.stubGlobal("fetch", fetchStub);
    const { unmount } = renderOps();
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
      const { container, unmount } = renderOps();
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
    // CostChart reads prefers-reduced-motion, which jsdom does not implement.
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }));
    const { container } = render(
      <CostChart dailyCosts={[{ date: "2026-10-31", cost: 0, tokens: 0 }]} modelUsage={[]} totalCost={0} totalTokens={0} />
    );
    expect(container.textContent).not.toMatch(/NaN|Infinity/);
    expect(container.textContent).toContain("$0.0000");
  });
});

const active = (id: string, extra = {}) => ({
  session_id: id, status: "running", step_count: 3, steps_completed: 1, tool_calls: 1, elapsed_events: 12, ...extra,
});

describe("/ops active sessions", () => {
  async function openActive() {
    renderOps();
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: /Active Sessions/ }));
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  it("a failed fetch is an error with Retry, not 'No sessions currently running'", async () => {
    await openActive(); // every request fails in beforeEach
    expect(screen.getByText("Couldn't load active sessions")).toBeTruthy();
    expect(screen.queryByText("No sessions currently running.")).toBeNull();
  });

  it("links each id to its session page and pluralises the counts", async () => {
    vi.stubGlobal(
      "fetch",
      backend({ "/sessions/active?limit=20": () => json({ ok: true, data: { sessions: [active("abc"), active("xyz", { tool_calls: 2, step_count: 1 })], total: 2, limit: 20 } }) })
    );
    await openActive();
    expect(screen.getByRole("link", { name: "abc" }).getAttribute("href")).toBe("/sessions/abc");
    expect(screen.getByText(/1 tool call(?!s)/)).toBeTruthy();
    expect(screen.getByText(/2 tool calls/)).toBeTruthy();
    expect(screen.getByText(/1\/3 steps/)).toBeTruthy();
    expect(screen.getByText(/1\/1 step(?!s)/)).toBeTruthy();
  });

  it("an empty list says so", async () => {
    vi.stubGlobal("fetch", backend({ "/sessions/active?limit=20": () => json({ ok: true, data: { sessions: [], total: 0, limit: 20 } }) }));
    await openActive();
    expect(screen.getByText("No sessions currently running.")).toBeTruthy();
  });
});

describe("/ops tab in the URL", () => {
  it("opens the tab named by ?tab= and writes a selection back", async () => {
    nav.store.search = "tab=logs";
    renderOps();
    await act(async () => {});
    expect(screen.getByRole("log", { name: "Live event log" })).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    });
    expect(nav.store.search).toBe(""); // the default drops the parameter
    expect(screen.queryByRole("log")).toBeNull();
  });
});

describe("/ops live log", () => {
  it("keeps a row's DOM node when the window slides (ids assigned at ingestion)", async () => {
    await openLiveTab();
    act(() => sockets.last.accept());
    act(() => sockets.last.emit({ type: "a", timestamp: "2026-10-31T10:11:12Z" }));
    const log = screen.getByRole("log");
    const first = log.firstElementChild;
    act(() => sockets.last.emit({ type: "b", timestamp: "2026-10-31T10:11:13Z" }));
    expect(log.firstElementChild).toBe(first);
  });

  it("shows the time in the reader's zone and names the full frame in a title", async () => {
    await openLiveTab();
    act(() => sockets.last.accept());
    act(() => sockets.last.emit({ type: "t", timestamp: "2026-10-31T10:11:12Z" }));
    expect(screen.getByText("10:11:12 AM")).toBeTruthy(); // exact: the raw frame text also holds 10:11:12Z
    expect(document.querySelector('span.truncate[title*="\\"type\\":\\"t\\""]')).not.toBeNull();
  });

  it("Clear Log empties the log and Undo on the toast brings it back", async () => {
    await openLiveTab();
    act(() => sockets.last.accept());
    act(() => sockets.last.emit({ type: "keep_me", timestamp: "2026-10-31T10:11:12Z" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Clear Log" }));
    });
    expect(screen.queryByText("keep_me")).toBeNull();
    expect(screen.getByText("Log cleared")).toBeTruthy();

    act(() => sockets.last.emit({ type: "after", timestamp: "2026-10-31T10:11:13Z" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    });
    const types = [...screen.getByRole("log").querySelectorAll("[data-slot=badge]")].map((b) => b.textContent);
    expect(types).toEqual(["keep_me", "after"]);
  });

  it("announces the socket on a change only, never on mount", async () => {
    const status = () => screen.getAllByRole("status").find((el) => el.getAttribute("aria-live") === "polite")!;
    await openLiveTab();
    expect(status().textContent).toBe("");
    act(() => sockets.last.accept());
    expect(status().textContent).toContain("connected");
    act(() => sockets.last.serverClose());
    expect(status().textContent).toContain("disconnected");
  });
});

describe("/ops plan form", () => {
  async function openPlan() {
    renderOps();
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Plan Visualization" }));
    });
  }

  it("a second submit while the first is in flight sends one request", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/plan-viz")) {
          calls += 1;
          await new Promise((r) => setTimeout(r, 1000));
          return json(plan("a"));
        }
        return json({ detail: "boom" }, 500);
      })
    );
    await openPlan();
    fireEvent.change(screen.getByLabelText("Session ID"), { target: { value: "a" } });
    const form = screen.getByLabelText("Session ID").closest("form")!;
    await act(async () => {
      fireEvent.submit(form);
      fireEvent.submit(form);
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(calls).toBe(1);
    expect(screen.getByTestId("plan")).toBeTruthy();
  });

  it("an ok:false answer is an error state, announced as an alert", async () => {
    vi.stubGlobal("fetch", backend({ "/plan-viz": () => json({ ok: false }) }));
    await openPlan();
    await loadPlan("a");
    expect(screen.getByRole("alert").textContent).toContain("could not load that plan");
    expect(screen.queryByTestId("plan")).toBeNull();
  });
});
