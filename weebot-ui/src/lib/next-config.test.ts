import { describe, expect, it } from "vitest";
import nextConfig from "../../next.config.mjs";

// A `rewrites()` entry for /api/* runs before the dynamic route handler in
// src/app/api/[[...path]]/route.ts, so Next proxied the request itself and the handler's
// cross-site and Host checks never ran (seen on the dev server: a cross-site POST was
// forwarded to localhost:8000 and only failed because nothing listened there). It also
// ignored BACKEND_URL. The route handler is the one proxy.
describe("next.config", () => {
  it("declares no rewrite that would shadow the /api proxy route", async () => {
    expect(nextConfig.rewrites).toBeUndefined();
  });
});
