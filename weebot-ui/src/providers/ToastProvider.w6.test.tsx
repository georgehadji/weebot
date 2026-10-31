import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./ToastProvider";

function Trigger({ variant }: { variant?: "error" | "success" }) {
  const { toast } = useToast();
  return (
    <button onClick={() => toast({ title: "Heads up", variant, action: { label: "Undo", onClick: () => {} } })}>
      fire
    </button>
  );
}

const setup = (variant?: "error" | "success") => {
  render(
    <ToastProvider>
      <Trigger variant={variant} />
    </ToastProvider>
  );
  fireEvent.click(screen.getByText("fire"));
};

describe("W6 D6: a toast cannot fail on a capability gap", () => {
  afterEach(() => vi.unstubAllGlobals());

  // http://<lan-ip>:3000 is not a secure context: `crypto.randomUUID` is undefined there.
  it("shows an error toast when crypto.randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {});
    setup("error");
    expect(screen.getByText("Heads up")).toBeTruthy();
  });

  it("works when crypto itself is missing", () => {
    vi.stubGlobal("crypto", undefined);
    setup("success");
    expect(screen.getByText("Heads up")).toBeTruthy();
  });

  it("two toasts get distinct ids without randomUUID (both stay, each dismisses alone)", () => {
    vi.stubGlobal("crypto", {});
    setup("error");
    fireEvent.click(screen.getByText("fire"));
    expect(screen.getAllByText("Heads up")).toHaveLength(2);
    fireEvent.click(screen.getAllByLabelText("Dismiss notification")[0]);
    expect(screen.getAllByText("Heads up")).toHaveLength(1);
  });

  it("still works when randomUUID exists (no regression)", () => {
    setup("success");
    expect(screen.getByText("Heads up")).toBeTruthy();
  });
});

describe("W6 C6: a toast holds still while hovered OR focused", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  // VERIFIED, unfixed (W6 fix budget spent): flip to `it` once hover and focus are separate flags.
  it("the pointer leaving does not start the clock while keyboard focus is inside", () => {
    setup("success");
    const toast = screen.getByRole("status");
    const action = screen.getByText("Undo");
    fireEvent.mouseEnter(toast);
    fireEvent.focus(action);
    fireEvent.mouseLeave(toast);
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByText("Heads up")).toBeTruthy();
  });

  it("moving focus between the toast's own buttons does not release it, leaving does", () => {
    setup("success");
    const action = screen.getByText("Undo");
    const close = screen.getByLabelText("Dismiss notification");
    fireEvent.focus(action);
    fireEvent.blur(action);
    fireEvent.focus(close);
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByText("Heads up")).toBeTruthy();
    fireEvent.blur(close);
    act(() => vi.advanceTimersByTime(9_000));
    expect(screen.queryByText("Heads up")).toBeNull();
  });
});
