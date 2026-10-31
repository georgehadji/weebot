import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ToolCallRow } from "./ToolCallRow";
import { ToolEvent } from "@/types/events";

const tool = (result: string, over: Partial<ToolEvent> = {}): ToolEvent => ({
  id: "t", timestamp: "t", session_id: "s", type: "tool", tool_call_id: "c", tool_name: "bash",
  function_name: "run", function_args: {}, status: "called", result, ...over,
});
const preview = (result: string) => {
  render(<ToolCallRow event={tool(result)} />);
  fireEvent.click(screen.getByRole("button", { name: /bash/ }));
  return screen.getByLabelText("Tool result").textContent ?? "";
};

describe("ToolCallRow truncation", () => {
  it("never cuts an emoji in half at the preview limit (C1: lone surrogate renders as U+FFFD)", () => {
    const shown = preview("a".repeat(3999) + "\u{1F600}" + "tail");
    expect(shown).not.toMatch(/[\uD800-\uDBFF]$/);
  });
  it("boundary: a result exactly at the limit is shown whole, with no truncation notice", () => {
    expect(preview("a".repeat(4000))).toHaveLength(4000);
    expect(screen.queryByText(/Show all/)).toBeNull();
  });
  it("boundary: one character over truncates and offers Show all, which reveals everything", () => {
    expect(preview("a".repeat(4001))).toHaveLength(4000);
    fireEvent.click(screen.getByText("Show all"));
    expect(screen.getByLabelText("Tool result").textContent).toHaveLength(4001);
  });
});
