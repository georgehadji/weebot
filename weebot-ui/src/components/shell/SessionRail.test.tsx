import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionRail } from "./SessionRail";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => <a {...props}>{children}</a>,
}));

// The URL is the rail search's source of truth; `search` stands in for window.location.search.
const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

vi.mock("@/hooks/useSessionList", () => {
  const sessions = [
      {
        id: "active-1",
        user_id: "user",
        agent_id: "agent",
        status: "running",
        title: "Migrate authentication",
        context: {},
        created_at: "2026-10-24T00:00:00Z",
        updated_at: "2026-10-24T00:00:00Z",
        event_count: 2,
      },
      {
        id: "done-1",
        user_id: "user",
        agent_id: "agent",
        status: "completed",
        title: "Prepare release notes",
        context: {},
        created_at: "2026-10-24T00:00:00Z",
        updated_at: "2026-10-24T00:00:00Z",
        event_count: 4,
        models: ["openrouter/anthropic/claude-x", "deepseek/deepseek-v4"],
      },
  ];
  return {
    useSessionList: () => ({ state: { status: "ready", data: sessions }, sessions, reload: vi.fn() }),
  };
});

beforeEach(() => {
  nav.search = "";
  nav.replace.mockReset();
  vi.useFakeTimers();
  // useUrlState reads the live URL when it writes.
  window.history.replaceState(null, "", "/");
});
afterEach(() => vi.useRealTimers());

describe("SessionRail", () => {
  it("filters sessions and lets the operator clear the search", () => {
    render(<SessionRail />);

    const search = screen.getByLabelText("Search sessions") as HTMLInputElement;
    fireEvent.change(search, { target: { value: "release" } });

    expect(screen.queryByText("Migrate authentication")).toBeNull();
    expect(screen.getByText("Prepare release notes")).toBeDefined();

    fireEvent.click(screen.getByLabelText("Clear search"));
    expect(search.value).toBe("");
    expect(screen.getByText("Migrate authentication")).toBeDefined();
  });

  it("shows the models each session ran on", () => {
    render(<SessionRail />);
    expect(screen.getByText("claude-x, deepseek-v4")).toBeDefined();
  });
});

describe("SessionRail search lives in ?q=", () => {
  it("starts from ?q= and filters by it", () => {
    nav.search = "q=release";
    window.history.replaceState(null, "", "/?q=release");
    render(<SessionRail />);
    expect((screen.getByLabelText("Search sessions") as HTMLInputElement).value).toBe("release");
    expect(screen.queryByText("Migrate authentication")).toBeNull();
    expect(screen.getByText("Prepare release notes")).toBeDefined();
  });

  it("typing writes the URL once, after a pause, with replace", () => {
    render(<SessionRail />);
    const search = screen.getByLabelText("Search sessions");
    fireEvent.change(search, { target: { value: "r" } });
    fireEvent.change(search, { target: { value: "rel" } });
    expect(nav.replace).not.toHaveBeenCalled();
    act(() => void vi.advanceTimersByTime(300));
    expect(nav.replace).toHaveBeenCalledTimes(1);
    expect(nav.replace).toHaveBeenCalledWith("/?q=rel", { scroll: false });
  });

  it("the box is a named search input with the autofill hint off", () => {
    render(<SessionRail />);
    const search = screen.getByLabelText("Search sessions") as HTMLInputElement;
    expect(search.name).toBe("q");
    expect(search.type).toBe("search");
    expect(search.getAttribute("autocomplete")).toBe("off");
  });

  it("the new-session link says New Session", () => {
    render(<SessionRail />);
    expect(screen.getByRole("link", { name: "New Session" })).toBeDefined();
  });
});
