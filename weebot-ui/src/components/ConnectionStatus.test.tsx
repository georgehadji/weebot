/**
 * ConnectionStatus: only the error state is an alert, the API key form is a real form, removing
 * the key asks first, and a hidden tab does not poll. fetch and storage are stubbed.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ toast: vi.fn(), visible: true }));
vi.mock("@/providers/ToastProvider", () => ({ useToast: () => ({ toast: h.toast, dismiss: () => {} }) }));
vi.mock("@/hooks/usePageVisible", () => ({ usePageVisible: () => h.visible }));

import { ConnectionStatus } from "./ConnectionStatus";

function memoryStorage(): Storage {
  const data = new Map<string, string>();
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

const fetchMock = vi.fn();
const respond = (status: number) => fetchMock.mockResolvedValue({ ok: status < 300, status, json: async () => ({}) });

beforeEach(() => {
  vi.stubGlobal("localStorage", memoryStorage());
  vi.stubGlobal("sessionStorage", memoryStorage());
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  h.toast.mockReset();
  h.visible = true;
});
afterEach(() => vi.unstubAllGlobals());

describe("states and roles", () => {
  it("connecting and connected are status, not alert; only the error is an alert", async () => {
    let release!: () => void;
    fetchMock.mockReturnValueOnce(new Promise((r) => (release = () => r({ ok: true, status: 200 }))));
    render(<ConnectionStatus />);
    expect(screen.getByText("Connecting…")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    await act(async () => release());
    expect(await screen.findByText("Connected")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });

  it("a refused connection is an alert with the next retry time", async () => {
    fetchMock.mockRejectedValue(new Error("down"));
    render(<ConnectionStatus />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Cannot connect to backend");
    expect(alert.textContent).toMatch(/Next automatic retry at/);
    expect(alert.textContent).not.toContain("Retrying connection");
  });
});

describe("the API key form", () => {
  const field = () => screen.getByLabelText("API key") as HTMLInputElement;

  it("is a labelled password field that autofill and spellcheck leave alone", async () => {
    respond(401);
    render(<ConnectionStatus />);
    await screen.findByRole("alert");
    expect(field().type).toBe("password");
    expect(field().name).toBe("api-key");
    expect(field().getAttribute("autocomplete")).toBe("off");
    expect(field().getAttribute("spellcheck")).toBe("false");
  });

  it("an empty key shows an inline error instead of doing nothing", async () => {
    respond(401);
    render(<ConnectionStatus />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Save Key" }));
    expect(await screen.findByText("Enter an API key to save.")).toBeTruthy();
    expect(sessionStorage.getItem("weebot_api_key")).toBeNull();
    expect(field().getAttribute("aria-invalid")).toBe("true");
  });

  it("Enter submits through the form: the key is stored trimmed and sent on the next probe", async () => {
    respond(401);
    render(<ConnectionStatus />);
    await screen.findByRole("alert");
    respond(200);
    fireEvent.change(field(), { target: { value: "  secret  " } });
    fireEvent.submit(field().closest("form")!);
    await waitFor(() => expect(sessionStorage.getItem("weebot_api_key")).toBe("secret"));
    await waitFor(() => expect(fetchMock.mock.calls.at(-1)![1]).toEqual({ headers: { "X-API-Key": "secret" } }));
    expect(await screen.findByText("Connected")).toBeTruthy();
  });
});

describe("removing the key", () => {
  it("asks first, and only a confirm removes it and toasts", async () => {
    sessionStorage.setItem("weebot_api_key", "secret");
    respond(200);
    render(<ConnectionStatus />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove API Key" }));
    expect(await screen.findByRole("dialog", { name: "Remove the API key?" })).toBeTruthy();
    expect(sessionStorage.getItem("weebot_api_key")).toBe("secret");
    const confirm = screen.getAllByRole("button", { name: "Remove API Key" }).at(-1)!;
    fireEvent.click(confirm);
    await waitFor(() => expect(sessionStorage.getItem("weebot_api_key")).toBeNull());
    expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ title: "API key removed" }));
  });
});

describe("polling", () => {
  it("a hidden tab does not probe the backend", () => {
    h.visible = false;
    respond(200);
    render(<ConnectionStatus />);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
