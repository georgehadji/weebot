import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/sessions/x",
  useSearchParams: () => new URLSearchParams(search),
}));
// The tabs' own bodies are tested beside them; here only which one the dock shows.
vi.mock("./PlanTab", () => ({ PlanTab: () => <div>plan body</div> }));
vi.mock("./ToolsTab", () => ({ ToolsTab: () => <div>tools body</div> }));
vi.mock("./CostTab", () => ({ CostTab: () => <div>cost body</div> }));
vi.mock("./TrustTab", () => ({ TrustTab: () => <div>trust body</div> }));

import { MissionDock } from "./Dock";

beforeEach(() => {
  replace.mockClear();
  search = "";
  window.history.replaceState({}, "", "/sessions/x");
});

describe("MissionDock tab lives in the URL", () => {
  it("opens on Plan with no parameter", () => {
    render(<MissionDock sessionId="x" />);
    expect(screen.getByRole("tab", { name: "Plan" }).getAttribute("aria-selected")).toBe("true");
  });

  it("opens the tab named by ?dock=, so a reload or a shared link restores it", () => {
    search = "dock=cost";
    render(<MissionDock sessionId="x" />);
    expect(screen.getByRole("tab", { name: "Cost" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("cost body")).toBeTruthy();
  });

  it("choosing a tab writes it to the URL", () => {
    render(<MissionDock sessionId="x" />);
    fireEvent.click(screen.getByRole("tab", { name: "Tools" }));
    expect(replace).toHaveBeenLastCalledWith("/sessions/x?dock=tools", { scroll: false });
  });

  it("choosing Plan again drops the parameter", () => {
    search = "dock=cost";
    window.history.replaceState({}, "", "/sessions/x?dock=cost");
    render(<MissionDock sessionId="x" />);
    fireEvent.click(screen.getByRole("tab", { name: "Plan" }));
    expect(replace).toHaveBeenLastCalledWith("/sessions/x", { scroll: false });
  });

  it("boundary: an unknown ?dock= value falls back to Plan", () => {
    search = "dock=bogus";
    render(<MissionDock sessionId="x" />);
    expect(screen.getByRole("tab", { name: "Plan" }).getAttribute("aria-selected")).toBe("true");
  });
});
