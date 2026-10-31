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

// W4 (D5): the proxy answered every upstream with `response.json()`, so a non-JSON body
// became `null`, and a 204 (which cannot carry a body) made NextResponse.json throw and
// the handler answer 503 "Failed to connect" for a request that succeeded.
describe("the /api proxy preserves the upstream response", () => {
  const get = (upstream: Response) => {
    vi.stubGlobal("fetch", vi.fn(async () => upstream));
    return GET(new NextRequest("http://localhost:3000/api/sessions"), ctx);
  };

  it("D5: a 204 stays a 204 with no body", async () => {
    const res = await get(new Response(null, { status: 204 }));
    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
  });

  it("D5: a text/plain body (Prometheus metrics) is not rewritten to null", async () => {
    const res = await get(
      new Response("weebot_up 1\n", { status: 200, headers: { "content-type": "text/plain" } }),
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("text/plain");
    expect(await res.text()).toBe("weebot_up 1\n");
  });

  it("D5: a non-JSON error body keeps its status and text", async () => {
    const res = await get(new Response("Bad Gateway", { status: 502 }));
    expect(res.status).toBe(502);
    expect(await res.text()).toBe("Bad Gateway");
  });

  it("no-regression: a JSON body and its status pass through byte for byte", async () => {
    const res = await get(
      new Response('{"detail":"nope"}', { status: 404, headers: { "content-type": "application/json" } }),
    );
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ detail: "nope" });
  });

  it("no-regression: an unreachable backend is still a 503", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    const res = await GET(new NextRequest("http://localhost:3000/api/sessions"), ctx);
    expect(res.status).toBe(503);
  });
});
