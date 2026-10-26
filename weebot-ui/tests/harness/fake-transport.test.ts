/**
 * Harness self-test (W0/H1+H2): proves the fake transports and the fake-timer pattern
 * work before any candidate is judged with them. Not a defect test.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushStream, installFakeSse, installFakeWebSocket, sseFrame } from "./fake-transport";

describe("fake transport harness", () => {
  let sockets: ReturnType<typeof installFakeWebSocket>;
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

  it("records a socket, its frames, and its server-side close", () => {
    const socket = new WebSocket("ws://example.test/ws");
    const received: unknown[] = [];
    socket.onmessage = (event) => received.push(JSON.parse((event as MessageEvent).data));

    expect(sockets.last.url).toBe("ws://example.test/ws");
    sockets.last.accept();
    expect(socket.readyState).toBe(1);

    sockets.last.emit({ type: "message" });
    sockets.last.serverClose();
    expect(received).toEqual([{ type: "message" }]);
    expect(socket.readyState).toBe(3);
  });

  it("advances a reconnect delay deterministically", async () => {
    let opens = 0;
    const open = () => {
      opens += 1;
      const socket = new WebSocket("ws://example.test/ws");
      socket.onclose = () => setTimeout(open, 1000);
    };
    open();

    sockets.last.serverClose();
    expect(opens).toBe(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(opens).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(opens).toBe(2);
  });

  it("streams SSE bytes to a reader and ends cleanly", async () => {
    const response = await fetch("http://example.test/api/events/stream");
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();

    sse.last.push(sseFrame({ id: "e1", session_id: "s1" }));
    const first = await reader.read();
    expect(decoder.decode(first.value)).toContain('data: {"id":"e1","session_id":"s1"}');

    sse.last.end();
    await flushStream();
    expect((await reader.read()).done).toBe(true);
    expect(sse.last.aborted).toBe(false);
  });

  it("marks the stream aborted when the caller's signal fires", async () => {
    const controller = new AbortController();
    const response = await fetch("http://example.test/api/events/stream", {
      signal: controller.signal,
    });
    expect(response.body).toBeDefined();

    controller.abort();
    await flushStream();
    expect(sse.last.aborted).toBe(true);
  });
});
