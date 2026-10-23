import { describe, it, expect } from "vitest";
import { endpointsFrom } from "./endpoints";

// One home for the backend URLs (SSOT audit row 24). Eight files carried their
// own defaults, and useBehavior joined `/behavior/ws` to a base that either
// lacked `/api` (default) or already ended in `/ws` (the documented env value),
// so the behavior socket never reached `/api/behavior/ws`.
describe("endpointsFrom", () => {
  it("defaults to the local backend", () => {
    const e = endpointsFrom(undefined, undefined);
    expect(e.api).toBe("http://localhost:8000/api");
    expect(e.ws).toBe("ws://localhost:8000/ws");
    expect(e.behaviorWs).toBe("ws://localhost:8000/api/behavior/ws");
  });

  it("derives the behavior socket from a configured /ws URL", () => {
    const e = endpointsFrom("https://bot.example/api", "wss://bot.example/ws");
    expect(e.behaviorWs).toBe("wss://bot.example/api/behavior/ws");
    expect(e.origin).toBe("https://bot.example");
  });
});
