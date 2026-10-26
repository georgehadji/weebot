import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./ToastProvider";

function Trigger({ variant }: { variant?: "error" | "success" }) {
  const { toast } = useToast();
  return <button onClick={() => toast({ title: "Heads up", variant })}>fire</button>;
}

const setup = (variant?: "error" | "success") => {
  render(
    <ToastProvider>
      <Trigger variant={variant} />
    </ToastProvider>
  );
  fireEvent.click(screen.getByText("fire"));
};

describe("toast policy", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("an error stays until it is dismissed", () => {
    setup("error");
    act(() => vi.advanceTimersByTime(10 * 60_000));
    expect(screen.getByText("Heads up")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Dismiss notification"));
    expect(screen.queryByText("Heads up")).toBeNull();
  });

  it("other toasts go away after the default time", () => {
    setup("success");
    act(() => vi.advanceTimersByTime(7_000));
    expect(screen.getByText("Heads up")).toBeTruthy();
    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.queryByText("Heads up")).toBeNull();
  });

  it("hovering holds the clock until the pointer leaves", () => {
    setup("success");
    const toast = screen.getByRole("status");
    fireEvent.mouseEnter(toast);
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByText("Heads up")).toBeTruthy();
    fireEvent.mouseLeave(toast);
    act(() => vi.advanceTimersByTime(9_000));
    expect(screen.queryByText("Heads up")).toBeNull();
  });

  it("the notifications region is always mounted", () => {
    render(<ToastProvider>x</ToastProvider>);
    expect(screen.getByRole("region", { name: "Notifications" })).toBeTruthy();
  });
});
