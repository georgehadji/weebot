import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelInfo } from "@/types/events";
import { RoleModelsPanel } from "./RoleModelsPanel";

const models: ModelInfo[] = [
  { id: "openai/gpt-x", name: "GPT X", provider: "openai", tier: "premium", cost_per_1k_tokens: 0.002, context_window: 1000, strengths: [] },
  { id: "z-ai/glm", name: "GLM", provider: "z-ai", tier: "free", cost_per_1k_tokens: 0.001, context_window: 1000, strengths: [] },
];
const rows = [
  { role: "planner", default: ["openai/gpt-x"], override: null, effective: "openai/gpt-x" },
  { role: "planner_sub", default: [], override: "z-ai/glm", effective: "z-ai/glm" },
];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.unstubAllGlobals());

async function mount(put: (url: string) => Promise<Response> = async () => json({})) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
    init?.method === "PUT" || init?.method === "DELETE" ? put(String(url)) : json(rows)
  );
  vi.stubGlobal("fetch", fetchMock);
  render(<RoleModelsPanel models={models} />);
  await act(async () => {});
  return fetchMock;
}

describe("RoleModelsPanel", () => {
  it("labels raw role ids readably, names the default model, and never prints undefined", async () => {
    await mount();
    expect(screen.getByRole("combobox", { name: /Planner\b(?! \()/ }).textContent).toContain("Default · GPT X");
    expect(screen.getByRole("combobox", { name: /Planner \(sub-agent\)/ }).textContent).toContain("GLM");
    expect(document.body.textContent).not.toContain("undefined");
    expect(screen.getByRole("button", { name: "Reset Planner (sub-agent) to default" })).toBeTruthy();
  });

  it("picking a model from the Select saves it for that role", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent); // jsdom has none; base-ui's popup reads it
    const fetchMock = await mount();
    const trigger = screen.getByRole("combobox", { name: /^Planner(?! \()/ });
    trigger.focus();
    await act(async () => void fireEvent.keyDown(trigger, { key: "ArrowDown" }));
    const option = await screen.findByRole("option", { name: "GLM" });
    // Keyboard, not a click: base-ui ignores a synthetic click that follows the open too closely.
    for (let i = 0; i < 4 && option.getAttribute("data-highlighted") === null; i++) {
      await act(async () => void fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" }));
    }
    await act(async () => void fireEvent.keyDown(document.activeElement!, { key: "Enter" }));
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(String(put[0])).toContain("/models/roles/planner");
    expect(JSON.parse(String(put[1]!.body))).toEqual({ model: "z-ai/glm" });
  });

  it("keeps focus and blocks a second change while saving: aria-busy, not disabled", async () => {
    let finish!: () => void;
    const fetchMock = await mount(() => new Promise<Response>((resolve) => (finish = () => resolve(json({})))));
    const reset = screen.getByRole("button", { name: "Reset Planner (sub-agent) to default" });
    reset.focus();
    await act(async () => fireEvent.click(reset));
    expect(reset.getAttribute("aria-busy")).toBe("true");
    expect(reset.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(reset);
    const trigger = screen.getByRole("combobox", { name: /Planner \(sub-agent\)/ });
    expect(trigger.getAttribute("aria-busy")).toBe("true");
    expect(trigger.hasAttribute("disabled")).toBe(false);

    await act(async () => fireEvent.click(reset));
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(1);

    await act(async () => finish());
    expect(reset.getAttribute("aria-busy")).toBeNull();
  });

  it("a failed save gives the reason and a next step", async () => {
    await mount(async () => json({ detail: "boom" }, 500));
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: "Reset Planner (sub-agent) to default" }))
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/Couldn’t save this model \(.+\)\. Try again/);
  });

  it("Reset does nothing while the role already uses its default", async () => {
    const fetchMock = await mount();
    const reset = screen.getByRole("button", { name: "Reset Planner to default" });
    expect(reset.getAttribute("aria-disabled")).toBe("true");
    await act(async () => fireEvent.click(reset));
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  });
});
