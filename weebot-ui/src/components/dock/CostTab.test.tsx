import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const costSummary = vi.fn();
vi.mock("@/lib/api", () => ({ api: { ops: { costSummary: (h: number) => costSummary(h) } } }));

import { CostTab } from "./CostTab";

const summary = {
  total_cost: 1.23456,
  total_tokens: 1234567,
  calls: 1,
  window_hours: 24,
  by_model: { "gpt-x": { cost: 0.5, calls: 1 }, "claude-y": { cost: 0.7, calls: 2 } },
};

describe("CostTab", () => {
  beforeEach(() => {
    costSummary.mockReset();
  });

  it("formats money, counts and plurals through lib/format", async () => {
    costSummary.mockResolvedValue({ ok: true, data: summary });
    render(<CostTab />);
    expect(await screen.findByText("$1.2346")).toBeTruthy();
    expect(screen.getByText("1,234,567")).toBeTruthy();
    expect(screen.getByText("$0.5000 · 1 call")).toBeTruthy();
    expect(screen.getByText("$0.7000 · 2 calls")).toBeTruthy();
  });

  it("model names are not translated and keep a title for the clipped text", async () => {
    costSummary.mockResolvedValue({ ok: true, data: summary });
    render(<CostTab />);
    const model = await screen.findByText("gpt-x");
    expect(model.getAttribute("translate")).toBe("no");
    expect(model.getAttribute("title")).toBe("gpt-x");
  });

  it("boundary: a partial payload shows zeros, not NaN", async () => {
    costSummary.mockResolvedValue({ ok: true, data: { total_cost: null, total_tokens: undefined, by_model: null } });
    render(<CostTab />);
    expect(await screen.findByText("$0.0000")).toBeTruthy();
    expect(screen.getByText("No model calls in this window.")).toBeTruthy();
  });
});
