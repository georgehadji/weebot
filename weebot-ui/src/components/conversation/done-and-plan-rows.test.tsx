/**
 * Found on live session de5d0990: a failed run ended with a "Session completed" badge,
 * and the plan card copied as "1. 1.List all files" (a typed number inside a numbered list).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DoneRow } from "./StatusEventRow";
import { PlanReviewCard } from "@/components/PlanReviewCard";
import { announcementFor } from "@/lib/announce";
import { DoneEvent, PlanReviewEvent } from "@/types/events";

const base = { id: "e", timestamp: "t", session_id: "s" };

describe("the done row", () => {
  it("says a failed run failed", () => {
    const event: DoneEvent = { ...base, type: "done", status: "failed" };
    render(<DoneRow event={event} />);
    expect(screen.getByText("Session failed")).toBeTruthy();
    expect(announcementFor(event)).toBe("Session failed");
  });

  it("keeps saying completed for a run that worked, and for old events", () => {
    expect(announcementFor({ ...base, type: "done", status: "completed" })).toBe("Session completed");
    expect(announcementFor({ ...base, type: "done" })).toBe("Session completed");
  });
});

describe("the plan review card", () => {
  it("numbers each step once", () => {
    const event: PlanReviewEvent = {
      ...base,
      type: "plan_review",
      step_count: 2,
      plan_data: {
        steps: [
          { id: "1", description: "List all files", status: "pending" },
          { id: "2", description: "Create subfolders", status: "pending" },
        ],
      },
    } as PlanReviewEvent;
    const { container } = render(<PlanReviewCard event={event} />);
    const items = [...container.querySelectorAll("ol > li")].map((li) => li.textContent);
    expect(items).toEqual(["List all files", "Create subfolders"]);
  });
});
