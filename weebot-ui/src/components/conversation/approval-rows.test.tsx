import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToolApprovalRow } from "./StatusEventRow";
import { PlanReviewCard } from "@/components/PlanReviewCard";
import { PlanReviewEvent, ToolApprovalEvent } from "@/types/events";

const base = { id: "e", timestamp: "t", session_id: "s" };

const approval = (over: Partial<ToolApprovalEvent> = {}): ToolApprovalEvent => ({
  ...base,
  type: "tool_approval",
  tool_name: "advanced_browser",
  arguments: {},
  risk_level: "egress_guard",
  reason: "first_time_recipient",
  prompt: "Allow this call?",
  fingerprint: "f",
  allow_always: "arxiv.org",
  ...over,
});

describe("approval controls", () => {
  it("Approve once sends one reply, then 'Approved' replaces the buttons", async () => {
    const onReply = vi.fn();
    render(<ToolApprovalRow event={approval()} onReply={onReply} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve once" }));
    expect(await screen.findByText("Approved")).toBeTruthy();
    expect(onReply.mock.calls).toEqual([["approve"]]);
    expect(screen.queryByRole("button", { name: "Approve once" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
  });

  it("a reply that was not delivered keeps the buttons instead of saying Approved", async () => {
    const onReply = vi.fn().mockRejectedValue(new Error("Reply not sent"));
    render(<ToolApprovalRow event={approval()} onReply={onReply} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve once" }));
    await waitFor(() => expect(onReply).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve once" })).toBeTruthy());
    expect(screen.queryByText("Approved")).toBeNull();
  });

  it("a double click in the same tick sends one reply", async () => {
    const onReply = vi.fn();
    render(<ToolApprovalRow event={approval()} onReply={onReply} />);
    const approve = screen.getByRole("button", { name: "Approve once" });
    await act(async () => {
      fireEvent.click(approve);
      fireEvent.click(approve);
    });
    expect(onReply).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Approved")).toBeTruthy();
  });

  it("Decline sends 'no' and says Declined", async () => {
    const onReply = vi.fn();
    render(<ToolApprovalRow event={approval()} onReply={onReply} />);
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(await screen.findByText("Declined")).toBeTruthy();
    expect(onReply.mock.calls).toEqual([["no"]]);
  });

  it("Always allow asks first, naming the tool, and sends nothing until confirmed", async () => {
    const onReply = vi.fn();
    render(<ToolApprovalRow event={approval()} onReply={onReply} />);
    fireEvent.click(screen.getByRole("button", { name: "Always allow arxiv.org" }));
    expect(await screen.findByRole("dialog", { name: "Always allow advanced_browser?" })).toBeTruthy();
    expect(onReply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Always allow" }));
    await waitFor(() => expect(onReply.mock.calls).toEqual([["always"]]));
    expect(await screen.findByText("Always allowed: advanced_browser")).toBeTruthy();
  });

  it("cancelling the Always allow confirm leaves the buttons and sends nothing", async () => {
    const onReply = vi.fn();
    render(<ToolApprovalRow event={approval()} onReply={onReply} />);
    fireEvent.click(screen.getByRole("button", { name: "Always allow arxiv.org" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onReply).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Approve once" })).toBeTruthy();
  });

  it("hides the legacy typed-reply instruction in the web card", () => {
    const event = approval({
      tool_name: "bash",
      allow_always: undefined,
      prompt: "Allow this call?\nReply 'yes' to run this exact call once, or say what to do instead.",
    });
    render(<ToolApprovalRow event={event} onReply={vi.fn()} />);
    expect(screen.getByText("Allow this call?")).toBeTruthy();
    expect(screen.queryByText(/Reply 'yes'/)).toBeNull();
  });
});

describe("plan review card", () => {
  const plan = (): PlanReviewEvent => ({
    ...base,
    type: "plan_review",
    step_count: 0,
    plan_data: { steps: [] },
  });

  it("approves with one click, once, and becomes read-only", async () => {
    const onReply = vi.fn();
    render(<PlanReviewCard event={plan()} onReply={onReply} onRequestChanges={vi.fn()} />);
    const approve = screen.getByRole("button", { name: "Approve plan" });
    await act(async () => {
      fireEvent.click(approve);
      fireEvent.click(approve);
    });
    expect(onReply.mock.calls).toEqual([["approve"]]);
    expect(screen.getByText("Plan approved")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve plan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Request changes" })).toBeNull();
  });

  it("Request changes hands focus to the composer instead of sending anything", () => {
    const onReply = vi.fn();
    const onRequestChanges = vi.fn();
    render(<PlanReviewCard event={plan()} onReply={onReply} onRequestChanges={onRequestChanges} />);
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));
    expect(onRequestChanges).toHaveBeenCalledTimes(1);
    expect(onReply).not.toHaveBeenCalled();
  });

  it("counts steps with the right plural", () => {
    const one = { ...plan(), step_count: 1 };
    const { rerender } = render(<PlanReviewCard event={one} />);
    expect(screen.getByText(/1 step$/)).toBeTruthy();
    rerender(<PlanReviewCard event={{ ...one, step_count: 3 }} />);
    expect(screen.getByText(/3 steps$/)).toBeTruthy();
  });
});
