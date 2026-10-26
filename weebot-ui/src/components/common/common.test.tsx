import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";
import { StateView } from "./StateView";
import { StatusBadge } from "./StatusBadge";
import { statusInfo } from "./status";

describe("StateView", () => {
  const show = (data: string[]) => <p>{data.join(",")}</p>;

  it("shows a labelled skeleton while loading", () => {
    render(<StateView state={{ status: "loading" }} loadingLabel="Loading sessions">{show}</StateView>);
    expect(screen.getByRole("status", { name: "Loading sessions" })).toBeTruthy();
  });

  it("shows the data when ready, or the empty view when there is none", () => {
    const { rerender } = render(<StateView state={{ status: "ready", data: ["a", "b"] }} isEmpty={(d) => d.length === 0} empty={<p>nothing</p>}>{show}</StateView>);
    expect(screen.getByText("a,b")).toBeTruthy();
    rerender(<StateView state={{ status: "ready", data: [] }} isEmpty={(d) => d.length === 0} empty={<p>nothing</p>}>{show}</StateView>);
    expect(screen.getByText("nothing")).toBeTruthy();
  });

  it("shows the error with Retry, and keeps stale data underneath", () => {
    const retry = vi.fn();
    render(<StateView state={{ status: "error", message: "backend down", data: ["old"] }} errorTitle="Couldn't load" onRetry={retry}>{show}</StateView>);
    expect(screen.getByRole("alert").textContent).toContain("backend down");
    expect(screen.getByText("old")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("an error with no data shows only the message", () => {
    render(<StateView state={{ status: "error", message: "nope" }}>{show}</StateView>);
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});

describe("StatusBadge", () => {
  it("never relies on colour: each status has its own glyph and a label", () => {
    const statuses = ["pending", "running", "waiting", "completed", "failed"];
    const icons = new Set(statuses.map((s) => statusInfo(s).icon));
    expect(icons.size).toBe(statuses.length);
    const { container } = render(<StatusBadge status="failed" variant="icon" />);
    expect(container.querySelector("[aria-label='Failed']")).not.toBeNull();
  });

  it("the pill variant prints the label", () => {
    render(<StatusBadge status="waiting" />);
    expect(screen.getByText("Waiting for you")).toBeTruthy();
  });

  it("falls back to the raw status for an unknown one", () => {
    expect(statusInfo("mystery").label).toBe("mystery");
  });
});

describe("ConfirmDialog", () => {
  it("focuses the safe action and confirms with the destructive one", async () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog open onOpenChange={onOpenChange} title="Delete?" confirmLabel="Delete" destructive onConfirm={onConfirm} />
    );
    const cancel = await screen.findByRole("button", { name: "Cancel" });
    await vi.waitFor(() => expect(document.activeElement).toBe(cancel));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
