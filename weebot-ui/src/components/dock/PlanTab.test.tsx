import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "@/types/events";

// The tab's one live input: the session's event stream. The test plays the events.
let emit: (event: AgentEvent) => void = () => {};
vi.mock("@/hooks/useSessionEvents", () => ({
  useSessionEvents: (_id: string, onEvent: (event: AgentEvent) => void) => {
    emit = onEvent;
    return { isConnected: true };
  },
}));

const planViz = vi.fn();
vi.mock("@/lib/api", () => ({ api: { ops: { planViz: (id: string) => planViz(id) } } }));

import { PlanTab } from "./PlanTab";

const NODES = [
  { id: "step-1", label: "first", status: "completed" },
  { id: "step-2", label: "second", status: "pending" },
  { id: "step-3", label: "third", status: "pending" },
];

function ev(partial: Record<string, unknown>): AgentEvent {
  return { id: "e", timestamp: "t", ...partial } as unknown as AgentEvent;
}

async function renderTab() {
  render(<PlanTab sessionId="s1" />);
  await screen.findByText("1 of 3 done");
}

describe("PlanTab live updates", () => {
  beforeEach(() => {
    planViz.mockReset();
    planViz.mockResolvedValue({ ok: true, data: { plan: { nodes: NODES } } });
  });

  it("marks a step as current when its step event starts", async () => {
    await renderTab();
    act(() => emit(ev({ type: "step", step_id: "step-2", description: "second", status: "started" })));
    const current = screen.getAllByRole("listitem").filter((li) => li.getAttribute("aria-current") === "step");
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toContain("second");
  });

  it("counts a step as done when its step event completes", async () => {
    await renderTab();
    act(() => emit(ev({ type: "step", step_id: "step-2", description: "second", status: "completed" })));
    expect(screen.getByText("2 of 3 done")).toBeTruthy();
  });

  it("shows a failed step", async () => {
    await renderTab();
    act(() => emit(ev({ type: "step", step_id: "step-2", description: "second", status: "failed" })));
    expect(screen.getByRole("img", { name: "Failed" })).toBeTruthy();
  });

  it("takes a replanned plan from the plan event", async () => {
    await renderTab();
    const plan = {
      steps: [
        { id: "step-1", description: "first", status: "completed" },
        { id: "step-4", description: "a brand new step", status: "pending" },
      ],
    };
    act(() => emit(ev({ type: "plan", status: "updated", plan })));
    expect(screen.getByText("a brand new step")).toBeTruthy();
    expect(screen.queryByText("third")).toBeNull();
    expect(screen.getByText("1 of 2 done")).toBeTruthy();
  });

  it("ignores a step event for a step that is not in the plan", async () => {
    await renderTab();
    act(() => emit(ev({ type: "step", step_id: "nope", description: "x", status: "completed" })));
    expect(screen.getByText("1 of 3 done")).toBeTruthy();
  });

  it("ignores events that are not about the plan", async () => {
    await renderTab();
    act(() => emit(ev({ type: "tool", tool_call_id: "t", tool_name: "bash", status: "calling" })));
    expect(screen.getByText("1 of 3 done")).toBeTruthy();
  });

  it("shows the plan when the first plan event arrives for a session that had none", async () => {
    planViz.mockResolvedValue({ ok: true, data: { plan: null } });
    render(<PlanTab sessionId="s1" />);
    await waitFor(() => expect(screen.getByText(/hasn.t entered planning/)).toBeTruthy());
    const plan = { steps: [{ id: "step-1", description: "only step", status: "pending" }] };
    act(() => emit(ev({ type: "plan", status: "created", plan })));
    expect(await screen.findByText("only step")).toBeTruthy();
  });
});

describe("PlanTab load failure", () => {
  beforeEach(() => {
    planViz.mockReset();
  });

  it("shows the error through an alert with a Retry that loads the plan again", async () => {
    planViz.mockRejectedValueOnce(new Error("Cannot connect to backend"));
    planViz.mockResolvedValueOnce({ ok: true, data: { plan: { nodes: NODES } } });
    render(<PlanTab sessionId="s1" />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Cannot connect to backend");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("1 of 3 done")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("loading is one status with text for assistive tech", () => {
    planViz.mockReturnValue(new Promise(() => {}));
    render(<PlanTab sessionId="s1" />);
    expect(screen.getByRole("status").textContent).toBe("Loading plan…");
  });
});
