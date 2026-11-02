import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

// W4 (D4): fetchApi classified failures by substring of the message, so a backend
// `detail` that merely contains "connect" or "fetch" was replaced by the
// "Cannot connect to backend" text, and a network failure whose browser wording has
// neither word (Safari: "Load failed") was not classified at all.

afterEach(() => vi.unstubAllGlobals());

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

describe("fetchApi error mapping", () => {
  it("D4: keeps a backend detail that contains the word 'connect'", async () => {
    respond(409, { detail: "Cannot connect session to its runner" });
    await expect(api.sessions.run("s1")).rejects.toThrow("Cannot connect session to its runner");
  });

  it("D4: keeps a backend detail that contains the word 'fetch'", async () => {
    respond(502, { detail: "Failed to fetch model list" });
    await expect(api.models.list()).rejects.toThrow("Failed to fetch model list");
  });

  it("D4: a network failure is a connection error whatever the browser calls it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Load failed"))));
    await expect(api.models.list()).rejects.toThrow(/Cannot connect to backend/);
  });

  it("no-regression: Chrome's 'Failed to fetch' is still a connection error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(api.models.list()).rejects.toThrow(/Cannot connect to backend/);
  });

  it("422: a FastAPI validation detail (an array) is readable, not '[object Object]'", async () => {
    respond(422, {
      detail: [{ loc: ["body", "prompt"], msg: "Field required", type: "missing" }],
    });
    await expect(api.sessions.create({ prompt: "" })).rejects.toThrow("Field required");
  });

  it("boundary: a body with neither detail nor error falls back to the status", async () => {
    respond(500, {});
    await expect(api.models.list()).rejects.toThrow("HTTP 500");
  });

  it("boundary: a non-JSON error body falls back to the status text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>boom</html>", { status: 500, statusText: "Server Error" })),
    );
    await expect(api.models.list()).rejects.toThrow("Server Error");
  });
});
