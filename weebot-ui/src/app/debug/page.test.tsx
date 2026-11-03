import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket, type FakeWebSocketControl } from "../../../tests/harness/fake-transport";
import DebugPage from "./page";

let sockets: FakeWebSocketControl;
beforeEach(() => {
  sockets = installFakeWebSocket();
  vi.spyOn(console, "log").mockImplementation(() => {});
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {} });
});
afterEach(() => {
  sockets.restore();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("/debug page", () => {
  it("labels the session input, names the log region and generates the id after mount", async () => {
    render(<DebugPage />);
    await act(async () => {});
    const input = screen.getByLabelText("Session ID") as HTMLInputElement;
    expect(input.value).toMatch(/^test-session-\d+$/);
    expect(screen.getByRole("log", { name: "WebSocket log" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "WebSocket Debug Page" })).toBeTruthy();
    // It connects once, with the id it shows (no first connect with an empty id).
    expect(sockets.sockets).toHaveLength(1);
    expect(sockets.last.url).toContain(input.value);
  });

  it("keeps each line's DOM node when new lines arrive (stable keys)", async () => {
    render(<DebugPage />);
    await act(async () => {});
    act(() => sockets.last.accept());
    const log = screen.getByRole("log");
    const first = log.firstElementChild;
    act(() => sockets.last.emit("hello"));
    expect(log.firstElementChild).toBe(first);
    expect(log.textContent).toContain("MESSAGE");
  });
});
