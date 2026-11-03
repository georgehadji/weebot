import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CostChart } from "./CostChart";

// jsdom has no matchMedia, which the reduced-motion query needs.
beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => vi.unstubAllGlobals());

const daily = [
  { date: "2026-10-30", cost: 0.0012, tokens: 1500 },
  { date: "2026-10-31", cost: 0.005, tokens: 2500 },
  { date: "2026-11-01", cost: 0.0021, tokens: 900 },
];
const models = [
  { name: "alpha/model-a", cost: 0.003, usage: 1200 },
  { name: "beta/model-b", cost: 0.001, usage: 1 },
];

describe("CostChart", () => {
  it("formats currency and counts for the reader, never raw floats", () => {
    render(<CostChart dailyCosts={daily} modelUsage={models} totalCost={0.0083} totalTokens={4900} />);
    expect(screen.getByText("$0.0083")).toBeTruthy();
    expect(screen.getByText("4,900")).toBeTruthy();
  });

  it("derives the daily title from the data and keeps every card a subheading", () => {
    render(<CostChart dailyCosts={daily} modelUsage={models} totalCost={1} totalTokens={1} />);
    expect(screen.getByRole("heading", { name: "Daily Cost (Last 3 Days)" }).tagName).toBe("H3");
    expect(screen.queryAllByRole("heading", { level: 2 })).toHaveLength(0);
  });

  it("gives each chart a summary label and the same numbers as a table", () => {
    render(<CostChart dailyCosts={daily} modelUsage={models} totalCost={1} totalTokens={1} />);
    const bar = screen.getByRole("img", { name: /Daily cost bar chart over 3 days\. Highest: \$0\.0050 on Oct 31/ });
    const pie = screen.getByRole("img", { name: /Cost by model pie chart: alpha\/model-a 75%, beta\/model-b 25%/ });
    // The table sits beside the graphic: inside role=img it would be hidden from assistive tech.
    expect(bar.querySelector("table")).toBeNull();
    expect(pie.querySelector("table")).toBeNull();
    const table = screen.getByRole("table", { name: "Daily cost" });
    expect(within(table).getByRole("cell", { name: "Oct 31" })).toBeTruthy();
    expect(within(screen.getByRole("table", { name: "Cost by model" })).getByRole("cell", { name: "75%" })).toBeTruthy();
  });

  it("states each model's share as text and marks swatches decorative", () => {
    const { container } = render(<CostChart dailyCosts={daily} modelUsage={models} totalCost={1} totalTokens={1} />);
    const item = screen.getByTitle("alpha/model-a").closest("li")!;
    expect(item.textContent).toContain("(75%)");
    expect(item.textContent).toContain("1,200 calls");
    expect(screen.getByTitle("beta/model-b").closest("li")!.textContent).toContain("1 call");
    expect(container.querySelectorAll("li [aria-hidden='true'].rounded-full")).toHaveLength(2);
    expect(screen.getByTitle("alpha/model-a").className).toContain("truncate");
  });

  it("uses chart tokens, not hex colours", () => {
    const { container } = render(<CostChart dailyCosts={daily} modelUsage={models} totalCost={1} totalTokens={1} />);
    expect(container.innerHTML).not.toMatch(/#[0-9a-f]{6}/i);
    const swatch = container.querySelector<HTMLElement>("li [aria-hidden='true']")!;
    expect(swatch.style.backgroundColor).toBe("var(--chart-1)");
  });

  it("shows an empty state instead of a blank pie when no model has usage", () => {
    render(<CostChart dailyCosts={daily} modelUsage={[]} totalCost={0} totalTokens={0} />);
    expect(screen.getByText("No model usage yet.")).toBeTruthy();
    expect(screen.queryByRole("img", { name: /pie chart/ })).toBeNull();
    expect(screen.getAllByText("$0.0000").length).toBeGreaterThan(0);
  });

  it("a single day reads as the latest day", () => {
    render(<CostChart dailyCosts={daily.slice(0, 1)} modelUsage={models} totalCost={1} totalTokens={1} />);
    expect(screen.getByRole("heading", { name: "Daily Cost (Latest Day)" })).toBeTruthy();
  });
});
