import { afterEach, describe, expect, it, vi } from "vitest";
import { openSocket } from "./api";

const created: Array<{ url: string; protocols?: string | string[] }> = [];

class FakeSocket {
  constructor(url: string, protocols?: string | string[]) {
    created.push({ url, protocols });
  }
}

afterEach(() => {
  created.length = 0;
  vi.unstubAllGlobals();
});

describe("openSocket", () => {
  it("sends the key as a subprotocol, never in the URL", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    openSocket("ws://localhost:8000/ws", "k-123");
    expect(created[0].url).toBe("ws://localhost:8000/ws");
    expect(created[0].protocols).toEqual(["weebot.v1", "bearer.k-123"]);
  });

  it("offers no protocol when there is no key", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    openSocket("ws://localhost:8000/ws", null);
    expect(created[0].protocols).toBeUndefined();
  });
});

describe("openSocket, key that cannot be a subprotocol token", () => {
  // A subprotocol must be an RFC 7230 token; "/" and "=" (base64 padding) are not, and the
  // browser's WebSocket constructor throws SyntaxError. That threw out of an effect and took
  // the whole page to the error boundary.
  class StrictSocket {
    constructor(url: string, protocols?: string | string[]) {
      for (const p of [protocols ?? []].flat()) {
        if (!/^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(p)) throw new SyntaxError("invalid subprotocol");
      }
      created.push({ url, protocols });
    }
  }

  it("W4: does not throw; opens an unauthenticated socket instead", () => {
    vi.stubGlobal("WebSocket", StrictSocket);
    expect(() => openSocket("ws://localhost:8000/ws", "a/b==")).not.toThrow();
    expect(created[0].protocols).toBeUndefined();
  });

  it("no-regression: a token-safe key is still offered", () => {
    vi.stubGlobal("WebSocket", StrictSocket);
    openSocket("ws://localhost:8000/ws", "k.1_2-3");
    expect(created[0].protocols).toEqual(["weebot.v1", "bearer.k.1_2-3"]);
  });
});
