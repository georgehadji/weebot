import { act } from "@testing-library/react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider, useTheme } from "./ThemeProvider";

function Probe() {
  const { theme } = useTheme();
  return <button aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>{theme}</button>;
}
const tree = (
  <ThemeProvider>
    <Probe />
  </ThemeProvider>
);

// This Node's experimental localStorage is absent under jsdom; give the tests a real one.
const store = new Map<string, string>();
beforeEach(() => {
  store.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.className = "";
  document.body.innerHTML = "";
});

// The server cannot read localStorage, so it renders "dark"; the pre-hydration script has
// already put the stored theme on <html>. The first client render must agree with the server.
describe("W6 R5: ThemeProvider hydrates without a mismatch", () => {
  async function hydrateWithStored(stored: string | null) {
    const realWindow = window;
    vi.stubGlobal("window", undefined);
    const html = renderToString(tree);
    vi.stubGlobal("window", realWindow);
    if (stored) store.set("weebot_theme", stored);
    const host = document.createElement("div");
    host.innerHTML = html;
    document.body.append(host);
    const errors: unknown[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...a) => void errors.push(a));
    await act(async () => {
      hydrateRoot(host, tree, { onRecoverableError: (e) => errors.push(e) });
    });
    spy.mockRestore();
    return { host, errors };
  }

  // VERIFIED, unfixed (W6: fix exceeds the 15-line cap, see audit): flip to `it` once the first
  // client render stops reading localStorage.
  it("a stored light theme hydrates cleanly and ends up light", async () => {
    const { host, errors } = await hydrateWithStored("light");
    expect(errors).toEqual([]);
    expect(host.textContent).toBe("light");
    expect(host.querySelector("button")!.getAttribute("aria-label")).toBe("Switch to dark theme");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(store.get("weebot_theme")).toBe("light");
  });

  it("a stored dark theme hydrates cleanly (no regression)", async () => {
    const { host, errors } = await hydrateWithStored("dark");
    expect(errors).toEqual([]);
    expect(host.textContent).toBe("dark");
  });

  it("no stored theme hydrates cleanly as dark (boundary)", async () => {
    const { host, errors } = await hydrateWithStored(null);
    expect(errors).toEqual([]);
    expect(host.textContent).toBe("dark");
  });

  it("an unrecognised stored value falls back to dark, as the init script does (boundary)", async () => {
    const { host, errors } = await hydrateWithStored("sepia");
    expect(errors).toEqual([]);
    expect(host.textContent).toBe("dark");
  });
});
