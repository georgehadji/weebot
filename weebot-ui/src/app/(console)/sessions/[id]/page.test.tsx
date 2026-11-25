import { useEffect } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SessionPage from "./page";

const h = vi.hoisted(() => ({
  epoch: 0,
  presence: new Map<string, unknown>(),
  mounts: 0,
  unmounts: 0,
  status: "" as string,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "s1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/components/conversation/ConversationPane", () => ({
  ConversationPane: ({ status }: { status: string }) => {
    h.status = status;
    useEffect(() => {
      h.mounts += 1;
      return () => {
        h.unmounts += 1;
      };
    }, []);
    return <div data-testid="pane" />;
  },
}));
vi.mock("@/hooks/useSessionEvents", () => ({ useSessionEvents: () => ({ isConnected: true }) }));
vi.mock("@/hooks/useSessionPresence", () => ({ useSessionPresence: () => h.presence }));
vi.mock("@/hooks/useShellSlots", () => ({ useShellSlots: () => {} }));
vi.mock("@/providers/EventStreamProvider", () => ({ useEventStreamContext: () => ({ streamEpoch: h.epoch }) }));

const session = {
  id: "s1", user_id: "u", agent_id: "a", status: "completed", title: "T", context: {},
  created_at: "2026-10-31T00:00:00Z", updated_at: "2026-10-31T00:00:00Z", event_count: 0,
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

// Reset before each test: the previous test's pane unmounts in RTL's own cleanup, after ours.
beforeEach(() => {
  Object.assign(h, { epoch: 0, mounts: 0, unmounts: 0, status: "" });
  h.presence.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe("/sessions/[id] loading", () => {
  it("announces loading through one status wrapper, not an unlabelled spinner", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<SessionPage />);
    expect(screen.getByRole("status").textContent).toBe("Loading session…");
  });

  it("a failed history load keeps the session open, says so, and Retry refetches", async () => {
    let historyUp = false;
    const fetchStub = vi.fn(async (url: string) => {
      if (String(url).endsWith("/events")) return historyUp ? json([]) : json({ detail: "store offline" }, 503);
      return json(session);
    });
    vi.stubGlobal("fetch", fetchStub);
    render(<SessionPage />);
    await act(async () => {});
    expect(screen.getByTestId("pane")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("store offline");

    historyUp = true;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByTestId("pane")).toBeTruthy();
  });

  it("a failed session load is an error with Retry, not an empty page", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "gone" }, 404)));
    render(<SessionPage />);
    await act(async () => {});
    expect(screen.getByRole("alert").textContent).toContain("gone");
    expect(screen.queryByTestId("pane")).toBeNull();
  });
});

describe("X7: a presence reconnect refreshes the status without unmounting the conversation", () => {
  it("an epoch bump keeps the pane mounted and shows the refetched status", async () => {
    let served: unknown = { ...session, status: "running" };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/events") ? json([]) : json(served))));
    const { rerender } = render(<SessionPage />);
    await act(async () => {});
    expect(h.mounts).toBe(1);
    expect(h.status).toBe("running");

    served = { ...session, status: "failed", updated_at: "2026-10-31T01:00:00Z" };
    h.epoch = 1; // the presence socket reconnected
    rerender(<SessionPage />);
    expect(screen.queryByText("Loading session…")).toBeNull(); // no spinner
    await act(async () => {});

    expect(h.status).toBe("failed");
    expect(h.mounts).toBe(1);
    expect(h.unmounts).toBe(0);
  });

  it("a failed refresh keeps the loaded session and the pane", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    let down = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).endsWith("/events")) return json([]);
      return down ? json({ detail: "offline" }, 503) : json(session);
    }));
    const { rerender } = render(<SessionPage />);
    await act(async () => {});
    down = true;
    h.epoch = 1;
    rerender(<SessionPage />);
    await act(async () => {});
    expect(screen.getByTestId("pane")).toBeTruthy();
    expect(h.unmounts).toBe(0);
  });

  it("a refetched FAILED is not hidden behind an older 'running' presence frame", async () => {
    h.presence.set("s1", {
      type: "session_presence", about_session_id: "s1", status: "running", title: "",
      timestamp: "2026-10-31T00:30:00Z",
    });
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      String(url).endsWith("/events") ? json([]) : json({ ...session, status: "failed", updated_at: "2026-10-31T01:00:00Z" })
    ));
    render(<SessionPage />);
    await act(async () => {});
    expect(h.status).toBe("failed");
  });
});
