import { describe, expect, it } from "vitest";
import { isForeignMutation, isUntrustedHost } from "./proxy-guard";

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

// A hostile page can make its own domain resolve to 127.0.0.1 (DNS rebinding). The browser then
// treats http://evil.test:3000 as same origin, so isForeignMutation passes. The proxy forwards
// to a backend that trusts loopback, so the Host must be one of the operator's own names.
// Only when the backend is local: a UI in a container reaches the API over the bridge, which
// grants no loopback trust, and users there arrive by a LAN name.
describe("isUntrustedHost", () => {
  const LOCAL_API = "http://localhost:8000/api";
  const DOCKER_API = "http://weebot-api:8000/api";

  it.each([
    "localhost",
    "localhost:3000",
    "LOCALHOST:3000",
    "127.0.0.1:3000",
    "[::1]:3000",
  ])("trusts %s when the backend is local", (host) => {
    expect(isUntrustedHost(host, LOCAL_API, "")).toBe(false);
  });

  it.each([
    "evil.test",
    "evil.test:3000",
    "localhost.evil.test",
    "127.0.0.1.evil.test",
    "localhost@evil.test",
    "",
    null,
  ])("distrusts %s when the backend is local", (host) => {
    expect(isUntrustedHost(host, LOCAL_API, "")).toBe(true);
  });

  it("allows a configured name", () => {
    expect(isUntrustedHost("weebot.lan:3000", LOCAL_API, "weebot.lan, dash.test")).toBe(false);
    expect(isUntrustedHost("evil.weebot.lan", LOCAL_API, "weebot.lan")).toBe(true);
  });

  it("does not judge the host when the backend is not local", () => {
    expect(isUntrustedHost("192.168.1.5:3000", DOCKER_API, "")).toBe(false);
    expect(isUntrustedHost("evil.test", DOCKER_API, "")).toBe(false);
  });

  it("treats an IPv6 loopback backend as local", () => {
    expect(isUntrustedHost("evil.test", "http://[::1]:8000/api", "")).toBe(true);
  });
});
