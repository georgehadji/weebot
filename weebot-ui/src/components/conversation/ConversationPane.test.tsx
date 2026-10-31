/**
 * W2 — ConversationPane projection: what the person at the console actually sees.
 * The transport hook, API and composer are stubbed; reducer, renderer registry and the
 * stick-to-bottom hook are real.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentEvent } from "@/types/events";

const h = vi.hoisted(() => ({
  emit: null as null | ((e: unknown) => void),
  history: [] as unknown[],
}));

vi.mock("@/hooks/useSessionEvents", () => ({
  useSessionEvents: (_id: unknown, onEvent: (e: unknown) => void) => {
    h.emit = onEvent;
    return { isConnected: true };
  },
}));
vi.mock("@/lib/api", () => ({ api: { sessions: { events: () => Promise.resolve(h.history) } } }));
vi.mock("@/providers/AnnouncerProvider", () => ({ useAnnounce: () => () => {} }));
vi.mock("./Composer", () => ({ Composer: () => null }));
vi.mock("./RunControls", () => ({ RunControls: () => null }));

import { ConversationPane } from "./ConversationPane";

const base = { timestamp: "t", session_id: "s" };
const msg = (id: string, text: string): AgentEvent => ({ ...base, id, type: "message", role: "assistant", message: text });
const tool = (id: string, status: "calling" | "called", result?: string): AgentEvent => ({
  ...base, id, type: "tool", tool_call_id: "c1", tool_name: "bash", function_name: "run",
  function_args: {}, status, result,
});

const text = () => document.querySelector('[role="log"]')!.textContent ?? "";
const push = (e: AgentEvent) => act(() => h.emit!(e));

function mount(status: "running" | "completed" = "running", initialEvents: AgentEvent[] = []) {
  return render(<ConversationPane sessionId="s1" status={status} initialEvents={initialEvents} onSessionCreated={() => {}} />);
}

beforeEach(() => {
  h.history = [];
  h.emit = null;
});

describe("D11: events the timeline does not draw are not timeline rows", () => {
  it("a session holding only title/plan events still says it is waiting", () => {
    mount("running", [
      { ...base, id: "t1", type: "title", title: "A task" },
      { ...base, id: "p1", type: "plan", status: "created" },
    ] as AgentEvent[]);
    expect(text()).toContain("Waiting for events");
  });

  it("an event that renders nothing does not count as a new row for the jump pill", async () => {
    // The reader has scrolled up: the sentinel is out of view.
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(private cb: (e: { isIntersecting: boolean }[]) => void) {}
        observe() {
          this.cb([{ isIntersecting: false }]);
        }
        disconnect() {}
      }
    );
    mount("running", [msg("m1", "hello")]);
    await screen.findByText(/Jump to latest/);
    await push({ ...base, id: "t1", type: "title", title: "x" } as AgentEvent);
    await push({ ...base, id: "t2", type: "title", title: "y" } as AgentEvent);
    expect(screen.getByText(/Jump to latest/).textContent).not.toMatch(/new/);
    vi.unstubAllGlobals();
  });
});

describe("history refetch keeps the timeline in the order the server stored it", () => {
  it("events missed before the socket subscribed land before the later live ones", async () => {
    const { rerender } = mount("running", []);
    await push(msg("m3", "third"));
    h.history = [msg("m1", "first"), msg("m2", "second"), msg("m3", "third")];
    rerender(<ConversationPane sessionId="s1" status="completed" onSessionCreated={() => {}} />);
    await waitFor(() => expect(text()).toContain("first"));
    expect(text().indexOf("first")).toBeLessThan(text().indexOf("second"));
    expect(text().indexOf("second")).toBeLessThan(text().indexOf("third"));
  });

  it("a tool row whose `called` arrived live is not reverted by a replayed `calling`", async () => {
    const { rerender } = mount("running", []);
    await push(tool("t2", "called", "the output"));
    h.history = [tool("t1", "calling"), tool("t2", "called", "the output")];
    rerender(<ConversationPane sessionId="s1" status="completed" onSessionCreated={() => {}} />);
    await waitFor(() => expect(h.history.length).toBe(2));
    await act(async () => {});
    expect(screen.getByText("Done")).toBeTruthy();
    expect(screen.queryByLabelText("Running")).toBeNull();
  });

  it("no-regression: a settled session with nothing missed leaves the rows alone", async () => {
    const { rerender } = mount("running", [msg("m1", "first")]);
    h.history = [msg("m1", "first")];
    rerender(<ConversationPane sessionId="s1" status="completed" onSessionCreated={() => {}} />);
    await act(async () => {});
    expect(text()).toContain("first");
  });
});
