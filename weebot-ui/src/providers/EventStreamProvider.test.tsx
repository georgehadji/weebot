/**
 * Transport lifecycle — proof-of-defect tests for wave W1.
 *
 * Each test names the property it asserts. They were written against HEAD before the fix,
 * so the docstrings record which defect they reproduce:
 *   D1  — the connection mode must not claim a live feed after the SSE body ends
 *   D12 — SSE frames must be parsed per the wire format the backend emits (CRLF)
 *   D15 — tearing a connection down must not schedule a reconnect
 */

import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentEvent } from "@/types/events";
import { EventStreamProvider, useEventStreamContext } from "./EventStreamProvider";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import {
  FakeWebSocketControl,
  flushStream,
  installFakeSse,
  installFakeWebSocket,
  sseFrame,
} from "../../tests/harness/fake-transport";

const SESSION = "sess-1";

function wrapper({ children }: { children: React.ReactNode }) {
  return <EventStreamProvider>{children}</EventStreamProvider>;
}

/**
 * Drive the provider through its own fallback policy: five reconnect attempts after the
 * first drop, then the SSE fallback (EventStreamProvider's MAX_RECONNECT_ATTEMPTS).
 */
async function forceSseFallback(sockets: FakeWebSocketControl) {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      sockets.last.serverClose();
      await vi.advanceTimersByTimeAsync(16_000);
      await flushStream();
    });
  }
}

describe("EventStreamProvider — SSE fallback wire format", () => {
  let sockets: FakeWebSocketControl;
  let sse: ReturnType<typeof installFakeSse>;

  beforeEach(() => {
    vi.useFakeTimers();
    sockets = installFakeWebSocket();
    sse = installFakeSse();
  });

  afterEach(() => {
    sse.restore();
    sockets.restore();
    vi.useRealTimers();
  });

  it("D12: delivers a frame encoded the way sse_starlette encodes it (CRLF separators)", async () => {
    const events: AgentEvent[] = [];
    renderHook(() => useSessionEvents(SESSION, (event) => events.push(event)), { wrapper });

    await forceSseFallback(sockets);
    expect(sse.streams).toHaveLength(1);

    await act(async () => {
      sse.last.push(sseFrame({ id: "e1", type: "message", session_id: SESSION }));
      await flushStream();
    });

    expect(events.map((event) => event.id)).toEqual(["e1"]);
  });

  it("D12 boundary: still delivers a frame whose separators are bare LF", async () => {
    const events: AgentEvent[] = [];
    renderHook(() => useSessionEvents(SESSION, (event) => events.push(event)), { wrapper });

    await forceSseFallback(sockets);
    await act(async () => {
      sse.last.push(
        `event: message\ndata: ${JSON.stringify({ id: "lf-1", type: "message", session_id: SESSION })}\n\n`
      );
      await flushStream();
    });

    expect(events.map((event) => event.id)).toEqual(["lf-1"]);
  });

  it("D12 boundary: a frame split across two reads is delivered once, whole", async () => {
    const events: AgentEvent[] = [];
    renderHook(() => useSessionEvents(SESSION, (event) => events.push(event)), { wrapper });

    await forceSseFallback(sockets);
    await act(async () => {
      sse.last.push("event: message\r\ndata: {\"id\":\"split\",\"type\":\"message\",");
      await flushStream();
    });
    expect(events).toHaveLength(0);
    await act(async () => {
      sse.last.push(`"session_id":"${SESSION}"}\r\n\r\n`);
      await flushStream();
    });

    expect(events.map((event) => event.id)).toEqual(["split"]);
  });
});

describe("EventStreamProvider — mode after the SSE body ends", () => {
  let sockets: FakeWebSocketControl;
  let sse: ReturnType<typeof installFakeSse>;

  beforeEach(() => {
    vi.useFakeTimers();
    sockets = installFakeWebSocket();
    sse = installFakeSse();
  });

  afterEach(() => {
    sse.restore();
    sockets.restore();
    vi.useRealTimers();
  });

  it("D1: stops reporting a live subscription once the stream is over", async () => {
    const { result } = renderHook(
      () => {
        const { getSessionMode } = useEventStreamContext();
        return { mode: getSessionMode(SESSION), ...useSessionEvents(SESSION) };
      },
      { wrapper }
    );

    await forceSseFallback(sockets);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.isConnected).toBe(true);

    // The backend restarted: the body ends with no error frame.
    await act(async () => {
      sse.last.end();
      await flushStream();
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.mode).not.toBe("sse");
    expect(result.current.isConnected).toBe(false);
  });

  it("D1 boundary: a failed stream is not reported as live either", async () => {
    const { result } = renderHook(
      () => {
        const { getSessionMode } = useEventStreamContext();
        return { mode: getSessionMode(SESSION), ...useSessionEvents(SESSION) };
      },
      { wrapper }
    );

    await forceSseFallback(sockets);
    await act(async () => {
      sse.last.fail(new Error("socket hang up"));
      await flushStream();
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.mode).not.toBe("sse");
    expect(result.current.isConnected).toBe(false);
  });
});

describe("EventStreamProvider — teardown", () => {
  let sockets: FakeWebSocketControl;
  let sse: ReturnType<typeof installFakeSse>;

  beforeEach(() => {
    vi.useFakeTimers();
    sockets = installFakeWebSocket();
    sse = installFakeSse();
  });

  afterEach(() => {
    sse.restore();
    sockets.restore();
    vi.useRealTimers();
  });

  it("D15: unmounting the provider does not open a replacement socket", async () => {
    function Consumer() {
      useSessionEvents(SESSION);
      return null;
    }

    const app = render(
      <EventStreamProvider>
        <Consumer />
      </EventStreamProvider>
    );
    await act(async () => {
      await flushStream();
    });
    await act(async () => {
      sockets.last.accept();
    });
    const opened = sockets.sockets.length;

    app.unmount();
    await flushStream();
    await vi.advanceTimersByTimeAsync(30_000);
    await flushStream();

    expect(sockets.sockets.length).toBe(opened);
    expect(sse.streams).toHaveLength(0);
  });
});
