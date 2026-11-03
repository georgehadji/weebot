import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StepStatus } from "@/types/events";
import { PlanChecklist } from "./PlanChecklist";

const LONG =
  "Create the output directory Output/lyapunov-hamiltonian-brief/ and a notes file to collect raw findings";

function step(id: string, status: StepStatus, description = `step ${id}`) {
  return { id, status, description };
}

describe("PlanChecklist", () => {
  it("lists every step in order with its number", () => {
    render(<PlanChecklist steps={[step("a", "completed"), step("b", "pending"), step("c", "pending")]} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(within(items[0]).getByText("1")).toBeTruthy();
    expect(within(items[2]).getByText("step c")).toBeTruthy();
  });

  it("shows the whole step text, not a clipped line", () => {
    render(<PlanChecklist steps={[step("a", "pending", LONG)]} />);
    const text = screen.getByText(LONG);
    expect(text.className).not.toMatch(/truncate|line-clamp/);
  });

  it("names each status for assistive tech, not by colour alone", () => {
    render(<PlanChecklist steps={[step("a", "completed"), step("b", "failed"), step("c", "pending")]} />);
    expect(screen.getByRole("img", { name: "Completed" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Failed" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Pending" })).toBeTruthy();
  });

  it("marks the running step as the current one", () => {
    render(<PlanChecklist steps={[step("a", "completed"), step("b", "running"), step("c", "pending")]} />);
    const current = screen.getAllByRole("listitem").filter((li) => li.getAttribute("aria-current") === "step");
    expect(current).toHaveLength(1);
    expect(within(current[0]).getByText("step b")).toBeTruthy();
  });

  it("summarises progress above the list", () => {
    render(<PlanChecklist steps={[step("a", "completed"), step("b", "completed"), step("c", "pending")]} />);
    expect(screen.getByText("2 of 3 done")).toBeTruthy();
  });

  it("exposes progress as a progressbar that can be read on demand", () => {
    render(<PlanChecklist steps={[step("a", "completed"), step("b", "completed"), step("c", "pending")]} />);
    const bar = screen.getByRole("progressbar", { name: "Plan progress" });
    expect(bar.getAttribute("aria-valuenow")).toBe("2");
    expect(bar.getAttribute("aria-valuemax")).toBe("3");
    expect(bar.getAttribute("aria-valuetext")).toBe("2 of 3 done");
  });

  it("boundary: an empty plan is 0 of 0, not NaN", () => {
    render(<PlanChecklist steps={[]} />);
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("0");
  });

  it("is not a second live region", () => {
    const { container } = render(<PlanChecklist steps={[step("a", "completed")]} />);
    expect(container.querySelector("[aria-live], [role=status], [role=alert]")).toBeNull();
  });

  it("renders no map, zoom controls or diagram chrome", () => {
    const { container } = render(<PlanChecklist steps={[step("a", "pending")]} />);
    expect(container.querySelector(".react-flow")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
