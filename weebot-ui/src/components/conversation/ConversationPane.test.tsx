/**
 * W2 — ConversationPane projection: what the person at the console actually sees.
 * The transport hook, API and composer are stubbed; reducer, renderer registry and the
 * stick-to-bottom hook are real.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentEvent } from "@/types/events";

const h = vi.hoisted(() => ({
  emit: null as null | ((e: unknown) => void),
  reconnect: undefined as undefined | (() => void),
  history: [] as unknown[],
  // Promises handed out, in order, before falling back to `history`; lets a test settle them late.
  queue: [] as Promise<unknown[]>[],
  eventsFor: [] as string[],
  failEvents: false,
  eventsCalls: 0,
  announce: vi.fn(),
}));

vi.mock("@/hooks/useSessionEvents", () => ({
  useSessionEvents: (_id: unknown, onEvent: (e: unknown) => void, onReconnect?: () => void) => {
    h.emit = onEvent;
    h.reconnect = onReconnect;
    return { isConnected: true };
  },
}));
vi.mock("@/lib/api", () => ({
  api: {
    sessions: {
      events: (id: string) => {
        h.eventsCalls += 1;
        h.eventsFor.push(id);
        const queued = h.queue.shift();
        if (queued) return queued;
        return h.failEvents ? Promise.reject(new Error("offline")) : Promise.resolve(h.history);
      },
    },
  },
}));
vi.mock("@/providers/AnnouncerProvider", () => ({ useAnnounce: () => h.announce }));
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
  h.failEvents = false;
  h.eventsCalls = 0;
  h.queue = [];
  h.eventsFor = [];
  h.announce.mockReset();
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

describe("a failed session says why it stopped and how to continue", () => {
  it("shows the server's interruption reason next to a Continue action", () => {
    render(
      <ConversationPane
        sessionId="s1"
        status="failed"
        failureReason="interrupted: the server stopped while this session was running."
        onSessionCreated={() => {}}
      />
    );
    expect(screen.getByText(/interrupted: the server stopped/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy();
  });

  it("falls back to a plain explanation when no reason was stored", () => {
    render(<ConversationPane sessionId="s1" status="failed" onSessionCreated={() => {}} />);
    expect(screen.getByText(/stopped before finishing/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy();
  });

  it("a cancelled run is not called a failure, and can be continued", () => {
    render(<ConversationPane sessionId="s1" status="cancelled" onSessionCreated={() => {}} />);
    expect(screen.getByText("You cancelled this run.")).toBeTruthy();
    expect(screen.queryByText(/stopped before finishing/)).toBeNull();
    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy();
  });

  it("is hidden while the session is not failed", () => {
    render(<ConversationPane sessionId="s1" status="running" onSessionCreated={() => {}} />);
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
  });
});

describe("the history refresh failing is shown, with a retry", () => {
  it("a failed fetch shows an error banner, and Retry fetches again and clears it", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    h.failEvents = true;
    mount("completed");
    expect((await screen.findByRole("alert")).textContent).toContain("Couldn’t refresh the conversation");
    expect(h.eventsCalls).toBe(1);

    h.failEvents = false;
    h.history = [msg("m1", "recovered")];
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(text()).toContain("recovered"));
    expect(h.eventsCalls).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("waiting states are announced, since the log is not a live region", () => {
  it("an empty session announces that it is waiting", () => {
    mount("running");
    expect(h.announce).toHaveBeenCalledWith("Waiting for events…");
  });

  it("a session that becomes running announces it once; one opened mid-run says nothing", () => {
    const { rerender } = mount("completed", [msg("m1", "hi")]);
    expect(h.announce).not.toHaveBeenCalledWith("Agent is working…");
    rerender(<ConversationPane sessionId="s1" status="running" onSessionCreated={() => {}} />);
    expect(h.announce.mock.calls.filter((c) => c[0] === "Agent is working…")).toHaveLength(1);

    h.announce.mockReset();
    mount("running", [msg("m2", "hi")]);
    expect(h.announce).not.toHaveBeenCalledWith("Agent is working…");
  });
});

describe("X6: a stream that dropped and resumed recovers what it missed", () => {
  it("refetches history on reconnect while the run is still going, and shows the missed step", async () => {
    mount("running", [msg("m1", "first")]);
    expect(h.eventsCalls).toBe(0); // a running session does not fetch on its own

    h.history = [msg("m1", "first"), msg("m2", "published while the socket was down")];
    await act(async () => h.reconnect!());

    await waitFor(() => expect(text()).toContain("published while the socket was down"));
    expect(h.eventsCalls).toBe(1);
  });

  it("does not announce or duplicate an event the live stream already delivered", async () => {
    mount("running", []);
    await push(msg("m1", "live"));
    h.announce.mockReset();

    h.history = [msg("m1", "live")];
    await act(async () => h.reconnect!());

    await waitFor(() => expect(h.eventsCalls).toBe(1));
    expect(text().match(/live/g)).toHaveLength(1);
    expect(h.announce).not.toHaveBeenCalled();
  });

  it("shows a Retry-able error when the refetch after a reconnect fails", async () => {
    mount("running", []);
    h.failEvents = true;
    await act(async () => h.reconnect!());
    await waitFor(() => expect(h.eventsCalls).toBe(1));
    expect(document.body.textContent).toMatch(/offline/);
  });

  it("Retry refetches while the run is still going, and clears the error", async () => {
    mount("running", []);
    h.failEvents = true;
    await act(async () => h.reconnect!());
    await screen.findByText(/offline/);

    h.failEvents = false;
    h.history = [msg("m2", "recovered after retry")];
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(text()).toContain("recovered after retry"));
    expect(h.eventsCalls).toBe(2);
    expect(document.body.textContent).not.toMatch(/offline/);
  });

  it("a slow older refetch cannot overwrite a newer one", async () => {
    mount("running", []);
    let failOld!: (e: Error) => void;
    h.queue = [new Promise<unknown[]>((_, rej) => (failOld = rej)), Promise.resolve([msg("m2", "newer answer")])];

    await act(async () => h.reconnect!()); // slow request
    await act(async () => h.reconnect!()); // newer request, answered at once
    await waitFor(() => expect(text()).toContain("newer answer"));

    await act(async () => failOld(new Error("late failure")));
    expect(document.body.textContent).not.toMatch(/late failure/);
  });

  it("drops an answer that arrives after the session changed", async () => {
    const { rerender } = mount("running", []);
    let resolveOld!: (e: unknown[]) => void;
    h.queue = [new Promise<unknown[]>((res) => (resolveOld = res))];
    await act(async () => h.reconnect!());

    rerender(<ConversationPane sessionId="s2" status="running" onSessionCreated={() => {}} />);
    await act(async () => resolveOld([msg("old", "from the previous session")]));

    expect(h.eventsFor).toEqual(["s1"]);
    expect(text()).not.toContain("from the previous session");
  });

  it("drops an answer that arrives after the pane unmounted", async () => {
    const { unmount } = mount("running", []);
    let resolveOld!: (e: unknown[]) => void;
    h.queue = [new Promise<unknown[]>((res) => (resolveOld = res))];
    await act(async () => h.reconnect!());
    unmount();
    const warn = vi.spyOn(console, "error").mockImplementation(() => {});
    await act(async () => resolveOld([msg("late", "too late")]));
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});
