import { describe, expect, it } from "vitest";
import { isForeignMutation } from "./proxy-guard";

const h = (o: Record<string, string>) => new Headers(o);
const HOST = "localhost:3000";

describe("isForeignMutation", () => {
  it("lets reads through whatever the origin", () => {
    expect(isForeignMutation("GET", h({ "sec-fetch-site": "cross-site" }), HOST)).toBe(false);
    expect(isForeignMutation("HEAD", h({}), HOST)).toBe(false);
  });

  it("refuses a cross-site POST", () => {
    expect(isForeignMutation("POST", h({ "sec-fetch-site": "cross-site" }), HOST)).toBe(true);
  });

  it("refuses a same-site (other port or subdomain) POST", () => {
    expect(isForeignMutation("POST", h({ "sec-fetch-site": "same-site" }), HOST)).toBe(true);
  });

  it("accepts a same-origin POST", () => {
    expect(isForeignMutation("POST", h({ "sec-fetch-site": "same-origin" }), HOST)).toBe(false);
  });

  it("falls back to Origin when Fetch Metadata is absent", () => {
    expect(isForeignMutation("DELETE", h({ origin: "http://localhost:3000" }), HOST)).toBe(false);
    expect(isForeignMutation("DELETE", h({ origin: "http://evil.test" }), HOST)).toBe(true);
  });

  it("refuses a mutation that names no origin at all", () => {
    expect(isForeignMutation("PUT", h({}), HOST)).toBe(true);
  });

  it("refuses an unparseable Origin", () => {
    expect(isForeignMutation("POST", h({ origin: "null" }), HOST)).toBe(true);
  });
});
