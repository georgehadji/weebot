import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SessionPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "s1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/components/conversation/ConversationPane", () => ({
  ConversationPane: () => <div data-testid="pane" />,
}));
vi.mock("@/hooks/useSessionEvents", () => ({ useSessionEvents: () => ({ isConnected: true }) }));
vi.mock("@/hooks/useSessionPresence", () => ({ useSessionPresence: () => new Map() }));
vi.mock("@/hooks/useShellSlots", () => ({ useShellSlots: () => {} }));
vi.mock("@/providers/EventStreamProvider", () => ({ useEventStreamContext: () => ({ streamEpoch: 0 }) }));

const session = {
  id: "s1", user_id: "u", agent_id: "a", status: "completed", title: "T", context: {},
  created_at: "2026-10-31T00:00:00Z", updated_at: "2026-10-31T00:00:00Z", event_count: 0,
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

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
