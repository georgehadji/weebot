import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/sessions/x",
  useSearchParams: () => new URLSearchParams(search),
}));

import { useUrlState, withParam } from "./useUrlState";

beforeEach(() => {
  replace.mockClear();
  search = "";
  window.history.replaceState({}, "", "/sessions/x");
});

describe("withParam", () => {
  it("sets, replaces and removes a parameter, keeping the others", () => {
    expect(withParam("a=1", "dock", "cost", "plan")).toBe("a=1&dock=cost");
    expect(withParam("dock=cost", "dock", "tools", "plan")).toBe("dock=tools");
    expect(withParam("a=1&dock=cost", "dock", "plan", "plan")).toBe("a=1");
  });
});

describe("useUrlState", () => {
  it("reads the parameter, or the fallback when absent", () => {
    expect(renderHook(() => useUrlState("dock", "plan")).result.current[0]).toBe("plan");
    search = "dock=cost";
    expect(renderHook(() => useUrlState("dock", "plan")).result.current[0]).toBe("cost");
  });

  it("writes with replace and no scroll, and drops the param at the fallback", () => {
    const { result } = renderHook(() => useUrlState("dock", "plan"));
    act(() => result.current[1]("cost"));
    expect(replace).toHaveBeenLastCalledWith("/sessions/x?dock=cost", { scroll: false });

    window.history.replaceState({}, "", "/sessions/x?dock=cost");
    act(() => result.current[1]("plan"));
    expect(replace).toHaveBeenLastCalledWith("/sessions/x", { scroll: false });
  });
});
