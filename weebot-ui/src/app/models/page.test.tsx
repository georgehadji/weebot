import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ModelsPage from "./page";

const model = {
  id: "openai/gpt-x", name: "GPT X", provider: "openai", tier: "premium",
  cost_per_1k_tokens: 0.002, context_window: 1000, strengths: [],
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.unstubAllGlobals());

describe("/models load state (W5 exit criterion: Remote<T> + StateView)", () => {
  it("a failed load offers Retry, and Retry recovers", async () => {
    let up = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/models/roles")) return json([]);
        return up ? json([model]) : json({ detail: "boom" }, 500);
      })
    );
    render(<ModelsPage />);
    await act(async () => {});
    expect(screen.getByRole("alert").textContent).toContain("boom");

    up = true;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    });
    expect(screen.getByText("GPT X")).toBeTruthy();
    expect(screen.getByText("1 model available")).toBeTruthy();
  });

  it("shows a loading status first, then the models (no regression)", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/models/roles") ? json([]) : json([model]))));
    render(<ModelsPage />);
    expect(screen.getByRole("status", { name: "Loading models" })).toBeTruthy();
    await act(async () => {});
    expect(screen.getByText("GPT X")).toBeTruthy();
  });

  it("labels the price per 1M tokens: the backend sends per-1K, the card shows x1000", async () => {
    const priced = { ...model, cost_per_1k_tokens: 0.006 };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/models/roles") ? json([]) : json([priced]))));
    render(<ModelsPage />);
    await act(async () => {});
    expect(screen.getByText(/Cost per 1M tokens/)).toBeTruthy();
    expect(screen.getByText("$6.00")).toBeTruthy();
  });

  it("states the tier as text, groups cards under the provider heading and formats the context window", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/models/roles") ? json([]) : json([{ ...model, context_window: 128000 }]))));
    render(<ModelsPage />);
    await act(async () => {});
    expect(screen.getByText("premium")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: "GPT X" })).toBeTruthy();
    expect(screen.getByText("128,000 tokens")).toBeTruthy();
  });

  it("an empty catalogue renders the page with zero models (boundary)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json([])));
    render(<ModelsPage />);
    await act(async () => {});
    expect(screen.getByText("0 models available")).toBeTruthy();
  });
});
