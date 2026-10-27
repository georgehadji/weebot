import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST, GET } from "./route";

const ctx = { params: Promise.resolve({ path: ["sessions"] }) };

afterEach(() => vi.unstubAllGlobals());

function call(handler: typeof POST, init: { method: string; headers?: Record<string, string> }) {
  const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const req = new NextRequest("http://localhost:3000/api/sessions", {
    method: init.method,
    headers: init.headers,
    body: init.method === "GET" ? undefined : "{}",
  });
  return { fetchMock, response: handler(req, ctx) };
}

describe("the /api proxy", () => {
  it("refuses a cross-site POST without calling the backend", async () => {
    const { fetchMock, response } = call(POST, {
      method: "POST",
      headers: { "sec-fetch-site": "cross-site" },
    });
    expect((await response).status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards a same-origin POST with its content type and authorization", async () => {
    const { fetchMock, response } = call(POST, {
      method: "POST",
      headers: {
        "sec-fetch-site": "same-origin",
        "content-type": "text/plain",
        authorization: "Bearer k",
      },
    });
    expect((await response).status).toBe(200);
    const sent = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    const headers = sent.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("text/plain");
    expect(headers["Authorization"]).toBe("Bearer k");
  });

  it("still forwards a cross-site GET", async () => {
    const { response } = call(GET, { method: "GET", headers: { "sec-fetch-site": "cross-site" } });
    expect((await response).status).toBe(200);
  });
});
