import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAsyncAction } from "./useAsyncAction";

describe("useAsyncAction", () => {
  it("fires once when run() is called twice in the same tick", async () => {
    let release!: () => void;
    const action = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
    const { result } = renderHook(() => useAsyncAction(action));

    let first!: Promise<boolean>;
    let second!: Promise<boolean>;
    act(() => {
      first = result.current.run();
      second = result.current.run();
    });
    expect(result.current.state.status).toBe("pending");
    await act(async () => {
      release();
      await first;
    });
    expect(action).toHaveBeenCalledTimes(1);
    expect(await second).toBe(false);
    expect(result.current.state.status).toBe("done");
  });

  it("reports a failure as state, not a thrown rejection, and can run again", async () => {
    const action = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useAsyncAction(action));

    await act(async () => {
      expect(await result.current.run()).toBe(false);
    });
    expect(result.current.state).toEqual({ status: "error", error: "boom" });

    await act(async () => {
      expect(await result.current.run()).toBe(true);
    });
    expect(result.current.state.status).toBe("done");
  });

  it("passes arguments through and resets to idle", async () => {
    const action = vi.fn();
    const { result } = renderHook(() => useAsyncAction(action));
    await act(async () => {
      await result.current.run("a", 2);
    });
    expect(action).toHaveBeenCalledWith("a", 2);
    act(() => result.current.reset());
    expect(result.current.state.status).toBe("idle");
  });
});
