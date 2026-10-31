/**
 * The visualizer must draw the plan it is given *now*. reactflow is stubbed to capture the
 * nodes/edges the component hands it (jsdom has no layout engine for the real one).
 */
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const seen = vi.hoisted(() => ({ edges: [] as { id: string; source: string; target: string; style?: { stroke?: string } }[], nodes: [] as { id: string }[] }));

vi.mock("reactflow", async () => {
  const react = await import("react");
  return {
    __esModule: true,
    default: (p: { nodes: typeof seen.nodes; edges: typeof seen.edges }) => {
      seen.nodes = p.nodes;
      seen.edges = p.edges;
      return react.createElement("div");
    },
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    useNodesState: (init: unknown[]) => react.useState(init).concat(() => {}) as never,
    useEdgesState: (init: unknown[]) => react.useState(init).concat(() => {}) as never,
  };
});
vi.mock("reactflow/dist/style.css", () => ({}));

import { PlanVisualizer } from "./PlanVisualizer";

const step = (id: string, status: "pending" | "running" | "completed") => ({ id, description: id, status });

describe("PlanVisualizer", () => {
  it("edges follow the plan when step statuses change (they were frozen at first render)", () => {
    const { rerender } = render(<PlanVisualizer steps={[step("a", "pending"), step("b", "pending")]} />);
    expect(seen.edges[0].style?.stroke).toBe("#9ca3af");
    rerender(<PlanVisualizer steps={[step("a", "completed"), step("b", "running")]} />);
    expect(seen.edges[0].style?.stroke).toBe("#22c55e");
  });

  it("edges never reference a step that is no longer in the plan", () => {
    const { rerender } = render(<PlanVisualizer steps={[step("a", "pending"), step("b", "pending"), step("c", "pending")]} />);
    rerender(<PlanVisualizer steps={[step("x", "pending"), step("y", "pending")]} />);
    const nodeIds = new Set(seen.nodes.map((n) => n.id));
    expect(seen.edges.length).toBe(1);
    expect(seen.edges.every((e) => nodeIds.has(e.source) && nodeIds.has(e.target))).toBe(true);
  });

  it("boundary: an empty plan says so and draws no graph; one step has no edges", () => {
    const { container, rerender } = render(<PlanVisualizer steps={[]} />);
    expect(container.textContent).toContain("No plan steps available");
    rerender(<PlanVisualizer steps={[step("a", "pending")]} />);
    expect(seen.edges).toEqual([]);
  });
});
