import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { SessionRail } from "./SessionRail";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => <a {...props}>{children}</a>,
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

const refresh = vi.fn();
vi.mock("@/hooks/useSessionList", () => ({
  useSessionList: () => ({
    sessions: [
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
      },
    ],
    loading: false,
    error: null,
    refresh,
  }),
}));

describe("SessionRail", () => {
  it("filters sessions and lets the operator clear the search", () => {
    render(<SessionRail />);

    const search = screen.getByLabelText("Search sessions") as HTMLInputElement;
    fireEvent.change(search, { target: { value: "release" } });

    expect(screen.queryByText("Migrate authentication")).toBeNull();
    expect(screen.getByText("Prepare release notes")).toBeDefined();

    fireEvent.click(screen.getByLabelText("Clear session search"));
    expect(search.value).toBe("");
    expect(screen.getByText("Migrate authentication")).toBeDefined();
  });
});
