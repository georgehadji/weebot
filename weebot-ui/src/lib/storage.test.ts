import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readStored, subscribeStored, writeStored } from "./storage";
import { apiBase, apiKey, backendUrl, setApiKey, setConnection, wsUrl } from "./settings";

// This Node's experimental localStorage shadows jsdom's with an unusable stub, so give the tests
// real in-memory areas.
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, String(v)),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
    key: (i: number) => [...data.keys()][i] ?? null,
    get length() {
      return data.size;
    },
  };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", memoryStorage());
  vi.stubGlobal("sessionStorage", memoryStorage());
});

afterEach(() => vi.unstubAllGlobals());

describe("lib/storage", () => {
  it("round-trips and removes a value", () => {
    writeStored("local", "k", "v");
    expect(readStored("local", "k")).toBe("v");
    writeStored("local", "k", null);
    expect(readStored("local", "k")).toBeNull();
  });

  it("never throws when the Storage API throws (privacy mode, full quota)", () => {
    const throwing = () => {
      throw new Error("denied");
    };
    vi.stubGlobal("localStorage", { getItem: throwing, setItem: throwing, removeItem: throwing });
    expect(readStored("local", "k")).toBeNull();
    expect(writeStored("local", "k", "v")).toBe(false);
  });

  it("notifies this tab's subscribers on write, and stops after unsubscribe", () => {
    const listener = vi.fn();
    const off = subscribeStored("session", "k", listener);
    writeStored("session", "k", "1");
    expect(listener).toHaveBeenCalledTimes(1);
    writeStored("session", "other", "1");
    expect(listener).toHaveBeenCalledTimes(1);
    off();
    writeStored("session", "k", "2");
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("lib/settings", () => {
  it("defaults to same-origin", () => {
    expect(backendUrl()).toBeNull();
    expect(apiBase()).toBe("/api");
    expect(apiKey()).toBeNull();
  });

  it("builds the API base from a configured backend, trimming blanks and a trailing slash", () => {
    setConnection({ backendUrl: " http://127.0.0.1:8000/ ", wsUrl: "ws://127.0.0.1:8000/ws" });
    expect(apiBase()).toBe("http://127.0.0.1:8000/api");
    expect(wsUrl()).toBe("ws://127.0.0.1:8000/ws");
    setConnection({ backendUrl: "   ", wsUrl: "" });
    expect(apiBase()).toBe("/api");
    expect(wsUrl()).toBeNull();
  });

  it("keeps the API key in the session and clears it on a blank value", () => {
    setApiKey(" secret ");
    expect(apiKey()).toBe("secret");
    expect(localStorage.length).toBe(0);
    setApiKey("  ");
    expect(apiKey()).toBeNull();
  });
});
