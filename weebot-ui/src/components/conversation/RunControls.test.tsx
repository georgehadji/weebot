/**
 * RunControls: Interrupt asks first (the backend turns a cancelled session into `failed`, and
 * Continue then starts a new task rather than resuming), guards double sends, and on failure
 * says what to do next without echoing the raw server text.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ cancel: vi.fn(), toast: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { sessions: { cancel: h.cancel } } }));
vi.mock("@/providers/ToastProvider", () => ({ useToast: () => ({ toast: h.toast, dismiss: () => {} }) }));

import { RunControls } from "./RunControls";

beforeEach(() => {
  h.cancel.mockReset().mockResolvedValue({});
  h.toast.mockReset();
});

const open = () => fireEvent.click(screen.getByRole("button", { name: "Interrupt" }));
const confirm = () => fireEvent.click(confirmButton());
const confirmButton = () => screen.getAllByRole("button", { name: "Interrupt" }).at(-1)!;

describe("RunControls", () => {
  it("Interrupt cancels nothing until the dialog is confirmed", async () => {
    render(<RunControls sessionId="s1" />);
    open();
    expect(await screen.findByRole("dialog", { name: "Interrupt this run?" })).toBeTruthy();
    expect(h.cancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(h.cancel).not.toHaveBeenCalled();
  });

  it("confirming cancels the session once, toasts, and shows Interrupted", async () => {
    render(<RunControls sessionId="s1" />);
    open();
    await screen.findByRole("dialog");
    confirm();
    confirm(); // a second click in the same tick must not cancel twice
    await waitFor(() => expect(screen.getByText("Interrupted")).toBeTruthy());
    expect(h.cancel).toHaveBeenCalledTimes(1);
    expect(h.cancel).toHaveBeenCalledWith("s1");
    expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Session interrupted" }));
  });

  it("a failed cancel keeps the dialog open with a next step, not the raw server message", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    h.cancel.mockRejectedValueOnce(new Error("HTTP 500: stack trace"));
    render(<RunControls sessionId="s1" />);
    open();
    await screen.findByRole("dialog");
    confirm();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Reload the session");
    expect(alert.textContent).not.toContain("stack trace");
    expect(screen.queryByText("Interrupted")).toBeNull();
  });
});
