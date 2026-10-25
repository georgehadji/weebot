/**
 * Test harness for the live transports: a fake WebSocket, a fake SSE server, and the
 * fake-timer convention that goes with them.
 *
 * Why this exists: `EventStreamProvider` opens WebSockets and reads an SSE response
 * body, and `vitest.config.ts` installs no browser transport — jsdom's `WebSocket` would
 * attempt a real connection and jsdom's `fetch` returns a whole buffered body, not a
 * stream. Neither mechanism can be exercised without these stubs.
 *
 * Fake timers (W0/H2): reconnects are `setTimeout(open, 1000 * 2 ** n)`. A test must call
 * `vi.useFakeTimers()` and drive time with `await vi.advanceTimersByTimeAsync(ms)` — the
 * async variant also drains the microtasks the socket/stream callbacks are queued on.
 * Never assert reconnect behaviour with real timers: a wall-clock sleep proves nothing
 * and flakes.
 *
 * Usage:
 *   const sockets = installFakeWebSocket();
 *   const sse = installFakeSse();
 *   afterEach(() => { sockets.restore(); sse.restore(); });
 *
 * Nothing here changes production code, and nothing is installed unless a test asks.
 */

import { vi } from "vitest";

// ── fake WebSocket ────────────────────────────────────────────────

export interface FakeSocket {
  readonly url: string;
  readyState: number;
  /** Frames the provider sent us. */
  readonly sent: string[];
  /** True when the production code called `close()` (not the server). */
  clientClosed: boolean;
  /** Simulate the server accepting the connection. */
  accept(): void;
  /** Simulate a server frame; objects are JSON-encoded like the real backend. */
  emit(payload: unknown): void;
  /** Simulate the server closing the connection. */
  serverClose(code?: number): void;
}

class FakeWebSocket implements FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;

  readyState = 0;
  readonly sent: string[] = [];
  clientClosed = false;

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    sockets.push(this);
  }

  accept(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  emit(payload: unknown): void {
    const data = typeof payload === "string" ? payload : JSON.stringify(payload);
    this.onmessage?.({ data } as MessageEvent);
  }

  serverClose(): void {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code: 1006 } as CloseEvent);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  /** What the provider calls when it tears the connection down. */
  close(): void {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.clientClosed = true;
    this.readyState = FakeWebSocket.CLOSED;
    // Browsers dispatch `close` asynchronously; keep that ordering so a test can tell
    // a reconnect scheduled from the close handler apart from one scheduled inline.
    queueMicrotask(() => this.onclose?.({ code: 1000 } as CloseEvent));
  }
}

let sockets: FakeWebSocket[] = [];

export interface FakeWebSocketControl {
  readonly sockets: FakeWebSocket[];
  readonly last: FakeWebSocket;
  restore(): void;
}

/** Replace the global `WebSocket` with the fake and record every connection. */
export function installFakeWebSocket(): FakeWebSocketControl {
  sockets = [];
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  return {
    get sockets() {
      return sockets;
    },
    get last() {
      return sockets[sockets.length - 1];
    },
    restore() {
      vi.unstubAllGlobals();
      sockets = [];
    },
  };
}

// ── fake SSE server ───────────────────────────────────────────────

export interface FakeSseStream {
  readonly url: string;
  readonly headers: Record<string, string>;
  /** True once the client's AbortController fired (teardown or fallback switch). */
  readonly aborted: boolean;
  /** Push raw bytes, exactly as they would arrive on the wire. */
  push(text: string): void;
  /** End the body cleanly: the caller's `reader.read()` resolves `{done: true}`. */
  end(): void;
  /** Tear the body with an error, like a dropped connection. */
  fail(error?: Error): void;
}

export interface FakeSseControl {
  readonly streams: FakeSseStream[];
  readonly last: FakeSseStream;
  restore(): void;
}

interface SseOptions {
  /** HTTP status to answer with; non-200 still gets a body, as a real error page would. */
  status?: number;
}

/**
 * Replace the global `fetch` with one that answers every request with a streaming
 * `text/event-stream` body the test controls.
 */
export function installFakeSse(options: SseOptions = {}): FakeSseControl {
  const streams: FakeSseStream[] = [];
  const encoder = new TextEncoder();

  const fakeFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key] = value;
    });

    let controller: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    });

    let aborted = false;
    init?.signal?.addEventListener("abort", () => {
      aborted = true;
      try {
        controller.close();
      } catch {
        // already closed — nothing to release
      }
    });

    streams.push({
      url,
      headers,
      get aborted() {
        return aborted;
      },
      push(text) {
        controller.enqueue(encoder.encode(text));
      },
      end() {
        try {
          controller.close();
        } catch {
          // already closed
        }
      },
      fail(error = new Error("stream failed")) {
        controller.error(error);
      },
    });

    return new Response(body, {
      status: options.status ?? 200,
      headers: { "content-type": "text/event-stream" },
    });
  });

  vi.stubGlobal("fetch", fakeFetch);
  return {
    get streams() {
      return streams;
    },
    get last() {
      return streams[streams.length - 1];
    },
    restore() {
      vi.unstubAllGlobals();
    },
  };
}

// ── stream pumping ────────────────────────────────────────────────

/**
 * Let the SSE reader's promise chain settle: each `read()` resolution needs a turn,
 * and the provider's `while` loop awaits one per chunk.
 */
export async function flushStream(turns = 8): Promise<void> {
  for (let i = 0; i < turns; i += 1) {
    await Promise.resolve();
  }
}

/** A frame exactly as `sse_starlette` encodes it: CRLF separators (see the wave report). */
export function sseFrame(payload: unknown): string {
  return `event: message\r\ndata: ${JSON.stringify(payload)}\r\n\r\n`;
}
