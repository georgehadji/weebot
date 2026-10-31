/**
 * W3 — the composer's send path: phase (idle/sending/failed) x delivery (sending/sent/failed).
 * api and the toast are stubbed; the reducer, the draft storage and the hook are real.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MessageEvent } from "@/types/events";

const h = vi.hoisted(() => ({
  create: vi.fn(),
  run: vi.fn(),
  input: vi.fn(),
  toast: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: { sessions: { create: h.create, run: h.run, input: h.input } } }));
vi.mock("@/providers/ToastProvider", () => ({ useToast: () => ({ toast: h.toast, dismiss: () => {} }) }));

import { useComposer } from "./useComposer";

type Props = { sessionId: string | null };
function setup(initial: Props = { sessionId: "s1" }) {
  const onSessionCreated = vi.fn();
  const onOptimisticMessage = vi.fn();
  const onDelivery = vi.fn();
  const hook = renderHook((p: Props) => useComposer({ ...p, onSessionCreated, onOptimisticMessage, onDelivery }), {
    initialProps: initial,
  });
  return { ...hook, onSessionCreated, onOptimisticMessage, onDelivery };
}
const failedMsg = (id: string, message: string): MessageEvent => ({
  type: "message", id, timestamp: "t", session_id: "s1", role: "user", message, delivery: "failed",
});
const deferred = <T,>() => {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};
const sentId = (call = 0) => (h.input.mock.calls[call][2] as { clientMsgId: string }).clientMsgId;

beforeEach(() => {
  h.create.mockReset().mockResolvedValue({ id: "new1" });
  h.run.mockReset().mockResolvedValue({});
  h.input.mockReset().mockResolvedValue({});
  h.toast.mockReset();
  window.sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe("D7: a task that did not start is not silently shown as sent", () => {
  it("create ok + run fails: the session still opens, the row settles, and the user is told", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    h.run.mockRejectedValue(new Error("Failed to start task"));
    const { result, onDelivery, onSessionCreated } = setup({ sessionId: null });
    act(() => result.current.edit("do it"));
    act(() => result.current.submit());
    await waitFor(() => expect(onSessionCreated).toHaveBeenCalledWith("new1"));
    expect(onDelivery).toHaveBeenLastCalledWith(expect.any(String), "sent");
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ variant: "error", description: "Failed to start task" })
    );
  });

  it("create ok + run ok: no toast", async () => {
    const { result, onSessionCreated } = setup({ sessionId: null });
    act(() => result.current.edit("do it"));
    act(() => result.current.submit());
    await waitFor(() => expect(onSessionCreated).toHaveBeenCalledWith("new1"));
    expect(h.run).toHaveBeenCalledWith("new1");
    expect(h.toast).not.toHaveBeenCalled();
  });

  it("create fails: nothing opens, the row fails, the text returns, run is never called", async () => {
    h.create.mockRejectedValueOnce(new Error("boom"));
    const { result, onDelivery, onSessionCreated } = setup({ sessionId: null });
    act(() => result.current.edit("do it"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.state.phase).toBe("failed"));
    expect(onDelivery).toHaveBeenLastCalledWith(expect.any(String), "failed");
    expect(result.current.state.draft).toBe("do it");
    expect(onSessionCreated).not.toHaveBeenCalled();
    expect(h.run).not.toHaveBeenCalled();
    expect(h.toast).not.toHaveBeenCalled();
  });
});

describe("retry goes through the state machine", () => {
  it("a retry that succeeds leaves no stale 'Not sent' error behind", async () => {
    h.input.mockRejectedValueOnce(new Error("offline"));
    const { result } = setup();
    act(() => result.current.edit("hello"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.state.phase).toBe("failed"));

    act(() => result.current.retry(failedMsg(sentId(), "hello")));
    await waitFor(() => expect(h.input).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.state.phase).toBe("idle"));
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.draft).toBe(""); // the retried text left the box
  });

  it("while a retry is in flight the composer says sending", async () => {
    const d = deferred<unknown>();
    h.input.mockRejectedValueOnce(new Error("offline")).mockReturnValueOnce(d.promise);
    const { result } = setup();
    act(() => result.current.edit("hello"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.state.phase).toBe("failed"));
    act(() => result.current.retry(failedMsg(sentId(), "hello")));
    expect(result.current.state.phase).toBe("sending");
    await act(async () => d.resolve({}));
    expect(result.current.state.phase).toBe("idle");
  });

  it("a retry that fails again keeps the text and shows the new error", async () => {
    h.input.mockRejectedValueOnce(new Error("offline")).mockRejectedValueOnce(new Error("still offline"));
    const { result } = setup();
    act(() => result.current.edit("hello"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.state.phase).toBe("failed"));
    act(() => result.current.retry(failedMsg(sentId(), "hello")));
    await waitFor(() => expect(result.current.state.error).toBe("still offline"));
    expect(result.current.state.draft).toBe("hello");
  });

  it("a retry reuses the row's id as client_msg_id, so the echo settles the same row", async () => {
    const { result, onDelivery } = setup();
    act(() => result.current.retry(failedMsg("row-1", "hello")));
    await waitFor(() => expect(h.input).toHaveBeenCalled());
    expect(h.input).toHaveBeenCalledWith("s1", "hello", expect.objectContaining({ clientMsgId: "row-1" }));
    expect(onDelivery).toHaveBeenCalledWith("row-1", "sending");
    await waitFor(() => expect(onDelivery).toHaveBeenCalledWith("row-1", "sent"));
  });

  it("a retry while another send is in flight does not start a second send", async () => {
    const d = deferred<unknown>();
    h.input.mockReturnValueOnce(d.promise);
    const { result } = setup();
    act(() => result.current.edit("second"));
    act(() => result.current.submit());
    expect(result.current.state.phase).toBe("sending");
    act(() => result.current.retry(failedMsg("old", "first")));
    expect(h.input).toHaveBeenCalledTimes(1);
    await act(async () => d.resolve({}));
  });
});

describe("phase x delivery cells of the hook", () => {
  it("idle x failed: a stale failed row coexists with an idle composer after a later send succeeds", async () => {
    h.input.mockRejectedValueOnce(new Error("offline"));
    const { result, onDelivery } = setup();
    act(() => result.current.edit("A"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.state.phase).toBe("failed"));
    act(() => result.current.edit("B"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.state.phase).toBe("idle"));
    expect(result.current.state.error).toBeNull();
    expect(onDelivery.mock.calls.filter((c) => c[1] === "failed")).toHaveLength(1);
  });

  it("sending: a second submit (double Enter) is ignored, and the text is sent exactly once", async () => {
    const d = deferred<unknown>();
    h.input.mockReturnValueOnce(d.promise);
    const { result, onOptimisticMessage } = setup();
    act(() => result.current.edit("once"));
    act(() => result.current.submit());
    act(() => result.current.submit());
    expect(onOptimisticMessage).toHaveBeenCalledTimes(1);
    expect(h.input).toHaveBeenCalledTimes(1);
    await act(async () => d.resolve({}));
  });

  it("whitespace-only and empty drafts never send; the text is sent trimmed", async () => {
    const { result } = setup();
    act(() => result.current.edit("   \n"));
    act(() => result.current.submit());
    expect(h.input).not.toHaveBeenCalled();
    act(() => result.current.edit("  hi  "));
    act(() => result.current.submit());
    await waitFor(() => expect(h.input).toHaveBeenCalledWith("s1", "hi", expect.anything()));
  });

  it("the optimistic row is created sending, with the id that goes on the wire", async () => {
    const { result, onOptimisticMessage } = setup();
    act(() => result.current.edit("hi"));
    act(() => result.current.submit());
    const row = onOptimisticMessage.mock.calls[0][0] as MessageEvent;
    expect(row).toMatchObject({ role: "user", message: "hi", delivery: "sending", session_id: "s1" });
    await waitFor(() => expect(h.input).toHaveBeenCalled());
    expect(sentId()).toBe(row.id);
  });
});

describe("drafts", () => {
  it("restores a saved draft after mount, in StrictMode too", async () => {
    window.sessionStorage.setItem("weebot_draft:s1", "saved");
    const { result } = renderHook(
      () =>
        useComposer({ sessionId: "s1", onSessionCreated: vi.fn(), onOptimisticMessage: vi.fn(), onDelivery: vi.fn() }),
      { wrapper: StrictMode }
    );
    await waitFor(() => expect(result.current.state.draft).toBe("saved"));
    expect(window.sessionStorage.getItem("weebot_draft:s1")).toBe("saved");
  });

  it("a draft is stored per session and removed when sent", async () => {
    const { result } = setup();
    act(() => result.current.edit("typed"));
    expect(window.sessionStorage.getItem("weebot_draft:s1")).toBe("typed");
    act(() => result.current.submit());
    expect(window.sessionStorage.getItem("weebot_draft:s1")).toBeNull();
    await waitFor(() => expect(result.current.state.phase).toBe("idle"));
  });

  it("a throwing sessionStorage never breaks typing or sending", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const { result } = setup();
    act(() => result.current.edit("typed"));
    act(() => result.current.submit());
    await waitFor(() => expect(h.input).toHaveBeenCalled());
  });

  it.fails("GUARDED (callers key the pane): switching session in place does not carry the old draft into the new session", async () => {
    window.sessionStorage.setItem("weebot_draft:s2", "other");
    const { result, rerender } = setup({ sessionId: "s1" });
    act(() => result.current.edit("for s1"));
    rerender({ sessionId: "s3" });
    await waitFor(() => expect(result.current.state.draft).toBe(""));
    expect(window.sessionStorage.getItem("weebot_draft:s3")).toBeNull();
    expect(window.sessionStorage.getItem("weebot_draft:s1")).toBe("for s1");
    rerender({ sessionId: "s2" });
    await waitFor(() => expect(result.current.state.draft).toBe("other"));
  });
});
