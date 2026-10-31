/**
 * W3 — composer + timeline row together: what the person at the console sees across
 * composer phase (idle/sending/failed) x row delivery (sending/sent/failed).
 * Real ConversationPane, Composer, hook and reducer; api, the socket hook and the toast are stubbed.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentEvent } from "@/types/events";

const h = vi.hoisted(() => ({
  emit: null as null | ((e: unknown) => void),
  create: vi.fn(),
  run: vi.fn(),
  input: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/hooks/useSessionEvents", () => ({
  useSessionEvents: (_id: unknown, onEvent: (e: unknown) => void) => {
    h.emit = onEvent;
    return { isConnected: true };
  },
}));
vi.mock("@/lib/api", () => ({
  api: { sessions: { create: h.create, run: h.run, input: h.input, events: () => Promise.resolve([]) } },
}));
vi.mock("@/providers/AnnouncerProvider", () => ({ useAnnounce: () => () => {} }));
vi.mock("@/providers/ToastProvider", () => ({ useToast: () => ({ toast: h.toast, dismiss: () => {} }) }));
vi.mock("./RunControls", () => ({ RunControls: () => null }));

import { ConversationPane } from "./ConversationPane";
import { MessageRow } from "./MessageRow";

const box = () => screen.getByLabelText("Message weebot") as HTMLTextAreaElement;
const type = (text: string) => fireEvent.change(box(), { target: { value: text } });
const enter = (init: Record<string, unknown> = {}) => fireEvent.keyDown(box(), { key: "Enter", ...init });
const log = () => document.querySelector('[role="log"]')!.textContent ?? "";
const mount = (sessionId: string | null = "s1") =>
  render(<ConversationPane sessionId={sessionId} status="completed" onSessionCreated={() => {}} />);
const sentId = (call = 0) => (h.input.mock.calls[call][2] as { clientMsgId: string }).clientMsgId;
const echo = (id: string, message: string) =>
  act(() =>
    h.emit!({ type: "message", id, timestamp: "t", session_id: "s1", role: "user", message } as AgentEvent)
  );

beforeEach(() => {
  h.create.mockReset().mockResolvedValue({ id: "new1" });
  h.run.mockReset().mockResolvedValue({});
  h.input.mockReset().mockResolvedValue({});
  h.toast.mockReset();
  window.sessionStorage.clear();
});

describe("Enter handling", () => {
  it("Enter sends, Shift+Enter does not", async () => {
    mount();
    type("hello");
    enter({ shiftKey: true });
    expect(h.input).not.toHaveBeenCalled();
    enter();
    await waitFor(() => expect(h.input).toHaveBeenCalledTimes(1));
  });

  it("Enter confirming an IME candidate does not send (isComposing)", () => {
    mount();
    type("ά");
    fireEvent.keyDown(box(), { key: "Enter", isComposing: true });
    expect(h.input).not.toHaveBeenCalled();
  });

  it("Enter that confirms an IME candidate after compositionend (Safari: keyCode 229) does not send", () => {
    mount();
    type("ά");
    fireEvent.keyDown(box(), { key: "Enter", keyCode: 229 });
    expect(h.input).not.toHaveBeenCalled();
  });

  it("two Enters one after the other send one message", async () => {
    let release!: () => void;
    h.input.mockReturnValueOnce(new Promise((r) => (release = () => r({}))));
    mount();
    type("once");
    enter();
    enter();
    expect(h.input).toHaveBeenCalledTimes(1);
    await act(async () => release());
  });
});

describe("the failed path, through the real Retry button", () => {
  it("failed x failed: the row says Not sent and the composer says why and gives the text back", async () => {
    h.input.mockRejectedValueOnce(new Error("offline"));
    mount();
    type("hello");
    enter();
    expect((await screen.findByRole("alert")).textContent).toContain("Not sent: offline");
    expect(box().value).toBe("hello");
    expect(log()).toContain("Not sent");
  });

  it("retry via the row: failed x sending -> idle x sent, with no stale alert and the box empty", async () => {
    h.input.mockRejectedValueOnce(new Error("offline"));
    mount();
    type("hello");
    enter();
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(h.input).toHaveBeenCalledTimes(2));
    expect(sentId(1)).toBe(sentId(0)); // same row, same wire id
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(box().value).toBe("");
    expect(box().hasAttribute("aria-invalid")).toBe(false);
    await echo(sentId(0), "hello");
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
    expect(log()).not.toContain("Not sent");
    expect(log().match(/hello/g)).toHaveLength(1);
  });

  it("idle x sent: a message that went through shows no delivery chrome", async () => {
    mount();
    type("fine");
    enter();
    await waitFor(() => expect(h.input).toHaveBeenCalled());
    await echo(sentId(), "fine");
    expect(log()).not.toContain("Sending");
    expect(log()).not.toContain("Not sent");
  });

  it("sending x sending: both the row and the composer say Sending while in flight", async () => {
    let release!: () => void;
    h.input.mockReturnValueOnce(new Promise((r) => (release = () => r({}))));
    mount();
    type("slow");
    enter();
    expect(screen.getAllByText("Sending…")).toHaveLength(2);
    expect(box().value).toBe(""); // the box stays enabled and empty
    expect(box().disabled).toBe(false);
    await act(async () => release());
    await waitFor(() => expect(screen.queryByText("Sending…")).toBeNull());
  });

  it("sending x sent: the server's echo settles the row before the HTTP answer arrives", async () => {
    let release!: () => void;
    h.input.mockReturnValueOnce(new Promise((r) => (release = () => r({}))));
    mount();
    type("fast");
    enter();
    await echo(sentId(), "fast");
    expect(log()).not.toContain("Sending");
    await act(async () => release());
    expect(log().match(/fast/g)).toHaveLength(1);
  });
});

describe("failed x sent (observation, deferred)", () => {
  // The echo proves delivery (the reducer keeps the row "sent"), yet the HTTP error still
  // tells the composer "Not sent" and hands the text back: re-sending it would duplicate it.
  // The hook cannot see the row; the fix crosses useComposer, the pane and the reducer.
  it.fails("an HTTP error after the server echoed the message does not claim 'Not sent'", async () => {
    let fail!: () => void;
    h.input.mockReturnValueOnce(new Promise((_, rej) => (fail = () => rej(new Error("502")))));
    mount();
    type("echoed");
    enter();
    await echo(sentId(), "echoed");
    await act(async () => fail());
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("MessageRow", () => {
  const base = { type: "message" as const, id: "m", timestamp: "t", session_id: "s", role: "user" as const, message: "hi" };
  it("sending shows the spinner and no Retry", () => {
    render(<MessageRow event={{ ...base, delivery: "sending" }} onRetry={() => {}} />);
    expect(screen.getByText("Sending…")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("failed shows Not sent and a Retry that hands back the event; no Retry without a handler", () => {
    const onRetry = vi.fn();
    const ev = { ...base, delivery: "failed" as const };
    const { rerender } = render(<MessageRow event={ev} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledWith(ev);
    rerender(<MessageRow event={ev} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/Not sent/)).toBeTruthy();
  });
  it("no delivery (history, assistant) shows no chrome", () => {
    render(<MessageRow event={{ ...base, role: "assistant" }} />);
    expect(screen.queryByText(/Sending|Not sent/)).toBeNull();
  });
});
