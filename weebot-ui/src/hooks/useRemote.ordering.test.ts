import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRemote } from "./useRemote";

/** A load whose every call returns a promise the test settles by hand. */
function controlledLoad<T>() {
  const calls: { resolve: (v: T) => void; reject: (e: Error) => void }[] = [];
  const load = () =>
    new Promise<T>((resolve, reject) => {
      calls.push({ resolve, reject });
    });
  return { load, calls };
}

describe("useRemote: the newest response wins (W5 D8)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("an older poll that resolves late does not overwrite a newer payload", async () => {
    const { load, calls } = controlledLoad<string>();
    const { result } = renderHook(() => useRemote(load, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // second poll starts while the first is in flight
    });
    expect(calls).toHaveLength(2);

    await act(async () => calls[1].resolve("newer")); // newer request answers first
    await act(async () => calls[0].resolve("older")); // older answers late

    expect(result.current.state).toEqual({ status: "ready", data: "newer" });
  });

  it("an older failure that lands late does not replace a newer success with an error", async () => {
    const { load, calls } = controlledLoad<string>();
    const { result } = renderHook(() => useRemote(load, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    await act(async () => calls[1].resolve("newer"));
    await act(async () => calls[0].reject(new Error("stale blip")));

    expect(result.current.state).toEqual({ status: "ready", data: "newer" });
  });

  it("in-order responses still apply in order (no regression)", async () => {
    const { load, calls } = controlledLoad<string>();
    const { result } = renderHook(() => useRemote(load, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    await act(async () => calls[0].resolve("first"));
    expect(result.current.state).toEqual({ status: "ready", data: "first" });
    await act(async () => calls[1].resolve("second"));
    expect(result.current.state).toEqual({ status: "ready", data: "second" });
  });

  it("a single request with no poll resolves normally (boundary: pollMs undefined)", async () => {
    const { load, calls } = controlledLoad<number>();
    const { result } = renderHook(() => useRemote(load));
    await act(async () => calls[0].resolve(7));
    expect(result.current.state).toEqual({ status: "ready", data: 7 });
  });
});
