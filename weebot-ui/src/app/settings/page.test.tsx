import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnnouncerProvider } from "@/providers/AnnouncerProvider";
import SettingsPage from "./page";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => <a {...props}>{children}</a>,
}));

// This Node's experimental localStorage shadows jsdom's with an unusable stub.
function memoryStorage(seed: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(seed));
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

let local: Storage;
beforeEach(() => {
  local = memoryStorage({ weebot_backend_url: "http://10.0.0.5:9000" });
  vi.stubGlobal("localStorage", local);
  vi.stubGlobal("sessionStorage", memoryStorage());
});
afterEach(() => vi.unstubAllGlobals());

const renderPage = () =>
  render(
    <AnnouncerProvider>
      <SettingsPage />
    </AnnouncerProvider>
  );
const backend = () => screen.getByLabelText("Backend HTTP URL") as HTMLInputElement;
const ws = () => screen.getByLabelText("WebSocket URL") as HTMLInputElement;
const type = (el: HTMLInputElement, value: string) => fireEvent.change(el, { target: { value } });
const save = () => fireEvent.click(screen.getByRole("button", { name: "Save" }));

describe("/settings connection form", () => {
  it("shows the saved URL and builds URL inputs with the right attributes", () => {
    renderPage();
    expect(backend().value).toBe("http://10.0.0.5:9000");
    expect(backend().type).toBe("url");
    expect(backend().name).toBe("backend-url");
    expect(backend().getAttribute("autocomplete")).toBe("off");
    expect(backend().getAttribute("spellcheck")).toBe("false");
  });

  it("rejects an invalid URL inline and writes nothing", () => {
    renderPage();
    type(backend(), "not a url");
    save();
    expect(screen.getByRole("alert").textContent).toContain("Enter a full URL");
    expect(backend().getAttribute("aria-invalid")).toBe("true");
    expect(local.getItem("weebot_backend_url")).toBe("http://10.0.0.5:9000");
  });

  it("rejects a WebSocket URL with the wrong scheme", () => {
    renderPage();
    type(ws(), "http://localhost:8000/ws");
    save();
    expect(screen.getByRole("alert").textContent).toContain("ws://");
  });

  it("saves a valid pair, announces it, and the submit works from the form (Enter)", () => {
    renderPage();
    type(backend(), "https://api.example.com/");
    type(ws(), "wss://api.example.com/ws");
    fireEvent.submit(backend().closest("form")!);
    expect(local.getItem("weebot_backend_url")).toBe("https://api.example.com/");
    expect(local.getItem("weebot_ws_url")).toBe("wss://api.example.com/ws");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Saved")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Settings saved");
  });

  it("guards unload only while there are unsaved edits", async () => {
    renderPage();
    const unload = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(unload()).toBe(false);
    await act(async () => type(backend(), "http://other:1"));
    expect(unload()).toBe(true);
    await act(async () => save());
    expect(unload()).toBe(false);
  });
});
