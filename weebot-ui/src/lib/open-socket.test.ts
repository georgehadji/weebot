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
