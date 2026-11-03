import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSessionList } from "@/hooks/useSessionList";
import { ToastProvider } from "@/providers/ToastProvider";
import type { SessionPresenceEvent } from "@/types/events";
import SessionsPage from "./page";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => <a {...props}>{children}</a>,
}));
// The rail's live source, a store like the real hook's state. A delete now sends a presence
// frame with status "deleted" (D10).
let presence = new Map<string, SessionPresenceEvent>();
const listeners = new Set<() => void>();
const setPresence = (next: Map<string, SessionPresenceEvent>) => {
  presence = next;
  listeners.forEach((l) => l());
};
vi.mock("@/hooks/useSessionPresence", async () => {
  const { useSyncExternalStore } = await import("react");
  const subscribe = (l: () => void) => (listeners.add(l), () => listeners.delete(l));
  return { useSessionPresence: () => useSyncExternalStore(subscribe, () => presence) };
});
// The page test renders the hook outside the real transport provider; no reconnect here.
vi.mock("@/providers/EventStreamProvider", () => ({
  useEventStreamContext: () => ({ streamEpoch: 0 }),
}));

const row = (id: string) => ({
  id, user_id: "u", agent_id: "a", status: "completed", title: `Title ${id}`, context: {},
  created_at: "2026-10-31T00:00:00Z", updated_at: "2026-10-31T00:00:00Z", event_count: 1,
});

const deleted = (id: string) => ({
  id: `p-${id}`, type: "session_presence", session_id: "", timestamp: "2026-10-31T00:00:01Z",
  about_session_id: id, status: "deleted", title: "", step_count: 0, steps_completed: 0,
}) as SessionPresenceEvent;

function Rail() {
  return <ul aria-label="rail">{useSessionList().sessions.map((s) => <li key={s.id}>{`rail:${s.id}`}</li>)}</ul>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  presence = new Map();
});

describe("/sessions delete and the rail (W5 D10)", () => {
  it("a session deleted on the page leaves the rail once its deleted presence frame lands", async () => {
    let live = [row("s1"), row("s2")];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        live = live.filter((s) => !String(url).endsWith(s.id));
        setPresence(new Map([["s1", deleted("s1")]])); // what the backend now publishes
        return new Response("{}", { status: 200 });
      }
      return new Response(JSON.stringify({ sessions: live, total: live.length }), { status: 200 });
    }));
    render(<ToastProvider><Rail /><SessionsPage /></ToastProvider>);
    await act(async () => {});
    expect(screen.getByText("rail:s1")).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Delete session Title s1"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete session" }));
    });

    expect(screen.queryByText("Title s1")).toBeNull(); // the page converged
    expect(screen.queryByText("rail:s1")).toBeNull(); // and so did the rail
    expect(screen.getByText("rail:s2")).toBeTruthy();
  });
});

describe("/sessions list", () => {
  const page = (rows: ReturnType<typeof row>[], total = rows.length) =>
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") return new Response(JSON.stringify({ detail: "locked" }), { status: 409 });
      return new Response(JSON.stringify({ sessions: rows, total }), { status: 200 });
    });

  it("Load More widens the window when the backend has more sessions than shown", async () => {
    const fetchStub = page([row("s1")], 150);
    vi.stubGlobal("fetch", fetchStub);
    render(<ToastProvider><SessionsPage /></ToastProvider>);
    await act(async () => {});
    expect(screen.getByText("Showing 1 of 150")).toBeTruthy();
    expect(String(fetchStub.mock.calls[0][0])).toContain("limit=100");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Load More" }));
    });
    expect(String(fetchStub.mock.calls.at(-1)?.[0])).toContain("limit=200");
  });

  it("no Load More when everything is shown, and a single event is not pluralised", async () => {
    vi.stubGlobal("fetch", page([row("s1")]));
    render(<ToastProvider><SessionsPage /></ToastProvider>);
    await act(async () => {});
    expect(screen.queryByRole("button", { name: "Load More" })).toBeNull();
    expect(screen.getByText(/1 event(?!s)/)).toBeTruthy();
  });

  it("a failed removal keeps the dialog open and says why", async () => {
    vi.stubGlobal("fetch", page([row("s1")]));
    render(<ToastProvider><SessionsPage /></ToastProvider>);
    await act(async () => {});
    fireEvent.click(screen.getByLabelText("Delete session Title s1"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete session" }));
    });
    expect(screen.getByRole("alert").textContent).toContain("locked");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
  });
});
