import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSessionList } from "@/hooks/useSessionList";
import { ToastProvider } from "@/providers/ToastProvider";
import SessionsPage from "./page";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => <a {...props}>{children}</a>,
}));
// The rail's live source: no presence frames arrive, which is what a delete produces.
vi.mock("@/hooks/useSessionPresence", () => ({ useSessionPresence: () => new Map() }));

const row = (id: string) => ({
  id, user_id: "u", agent_id: "a", status: "completed", title: `Title ${id}`, context: {},
  created_at: "2026-10-31T00:00:00Z", updated_at: "2026-10-31T00:00:00Z", event_count: 1,
});

function Rail() {
  return <ul aria-label="rail">{useSessionList().sessions.map((s) => <li key={s.id}>{`rail:${s.id}`}</li>)}</ul>;
}

afterEach(() => vi.unstubAllGlobals());

describe("/sessions delete and the rail (W5 D10)", () => {
  it.fails("KNOWN DEFECT (escalated: cross-boundary): a session deleted on the page leaves the rail", async () => {
    let live = [row("s1"), row("s2")];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        live = live.filter((s) => !String(url).endsWith(s.id));
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
    expect(screen.queryByText("rail:s1")).toBeNull(); // the rail did not
  });
});
