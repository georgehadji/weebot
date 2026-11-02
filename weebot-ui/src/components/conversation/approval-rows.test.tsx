import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToolApprovalRow } from "./StatusEventRow";
import { PlanReviewCard } from "@/components/PlanReviewCard";
import { PlanReviewEvent, ToolApprovalEvent } from "@/types/events";

const base = { id: "e", timestamp: "t", session_id: "s" };

describe("approval controls", () => {
  it("submits the exact approval choices without requiring typed text", () => {
    const onReply = vi.fn();
    const event: ToolApprovalEvent = {
      ...base,
      type: "tool_approval",
      tool_name: "advanced_browser",
      arguments: {},
      risk_level: "egress_guard",
      reason: "first_time_recipient",
      prompt: "Allow this call?",
      fingerprint: "f",
      allow_always: "arxiv.org",
    };
    render(<ToolApprovalRow event={event} onReply={onReply} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve once" }));
    fireEvent.click(screen.getByRole("button", { name: "Always allow arxiv.org" }));
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(onReply.mock.calls).toEqual([["approve"], ["always"], ["no"]]);
  });

  it("hides the legacy typed-reply instruction in the web card", () => {
    const event: ToolApprovalEvent = {
      ...base,
      type: "tool_approval",
      tool_name: "bash",
      arguments: {},
      risk_level: "egress_guard",
      reason: "first_time_recipient",
      prompt: "Allow this call?\nReply 'yes' to run this exact call once, or say what to do instead.",
      fingerprint: "f",
    };
    render(<ToolApprovalRow event={event} onReply={vi.fn()} />);
    expect(screen.getByText("Allow this call?")).toBeTruthy();
    expect(screen.queryByText(/Reply 'yes'/)).toBeNull();
  });

  it("lets the operator approve a plan with one click", () => {
    const onReply = vi.fn();
    const event: PlanReviewEvent = {
      ...base,
      type: "plan_review",
      step_count: 0,
      plan_data: { steps: [] },
    };
    render(<PlanReviewCard event={event} onReply={onReply} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve plan" }));
    expect(onReply).toHaveBeenCalledWith("approve");
  });
});
