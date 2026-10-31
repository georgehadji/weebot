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
