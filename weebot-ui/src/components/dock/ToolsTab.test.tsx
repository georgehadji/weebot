import { act, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentEvent, ToolEvent } from "@/types/events";

let emit: (event: AgentEvent) => void = () => {};
vi.mock("@/hooks/useSessionEvents", () => ({
  useSessionEvents: (_id: string, onEvent: (event: AgentEvent) => void) => {
    emit = onEvent;
    return { isConnected: true };
  },
}));

import { ToolsTab } from "./ToolsTab";

function tool(id: string, status: "calling" | "called", extra: Partial<ToolEvent> = {}): AgentEvent {
  return {
    id: `e-${id}-${status}`,
    timestamp: "t",
    type: "tool",
    tool_call_id: id,
    tool_name: "bash",
    function_name: `run_${id}`,
    function_args: {},
    status,
    ...extra,
  } as unknown as AgentEvent;
}

describe("ToolsTab", () => {
  it("says so when there are no calls", () => {
    render(<ToolsTab sessionId="s" />);
    expect(screen.getByText("No tool calls yet.")).toBeTruthy();
  });

  it("lists calls as a list, newest first", () => {
    render(<ToolsTab sessionId="s" />);
    act(() => emit(tool("a", "calling")));
    act(() => emit(tool("b", "calling")));
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("run_b")).toBeTruthy();
  });

  it("a later event for the same call updates it in place instead of adding a row", () => {
    render(<ToolsTab sessionId="s" />);
    act(() => emit(tool("a", "calling")));
    act(() => emit(tool("b", "calling")));
    act(() => emit(tool("a", "called")));
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[1]).getByText("run_a")).toBeTruthy();
    expect(within(items[1]).getByText("Done")).toBeTruthy();
    expect(within(items[0]).getByText("Running")).toBeTruthy();
  });

  it("marks a failed call, with identifiers excluded from translation and a title for the clipped text", () => {
    render(<ToolsTab sessionId="s" />);
    act(() => emit(tool("a", "called", { is_error: true })));
    expect(screen.getByText("Failed")).toBeTruthy();
    const name = screen.getByText("run_a");
    expect(name.getAttribute("translate")).toBe("no");
    expect(name.getAttribute("title")).toBe("run_a");
    expect(name.className).toContain("truncate");
  });

  it("is not a live region (failures go through the announcer)", () => {
    const { container } = render(<ToolsTab sessionId="s" />);
    act(() => emit(tool("a", "called", { is_error: true })));
    expect(container.querySelector("[aria-live], [role=status], [role=alert]")).toBeNull();
  });

  it("ignores events that are not tool events", () => {
    render(<ToolsTab sessionId="s" />);
    act(() => emit({ id: "e", timestamp: "t", type: "done" } as unknown as AgentEvent));
    expect(screen.getByText("No tool calls yet.")).toBeTruthy();
  });
});
