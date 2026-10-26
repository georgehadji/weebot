import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useRemote } from "./useRemote";

describe("useRemote", () => {
  it("goes loading -> ready", async () => {
    const load = () => Promise.resolve([1, 2]);
    const { result } = renderHook(() => useRemote(load));
    expect(result.current.state.status).toBe("loading");
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: [1, 2] }));
  });

  it("goes loading -> error with the message", async () => {
    const load = () => Promise.reject(new Error("backend down"));
    const { result } = renderHook(() => useRemote(load));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", message: "backend down" }));
  });

  it("keeps the last good data when a refresh fails, and retry recovers", async () => {
    let calls = 0;
    const load = () => {
      calls += 1;
      return calls === 2 ? Promise.reject(new Error("blip")) : Promise.resolve([calls]);
    };
    const { result } = renderHook(() => useRemote(load));
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: [1] }));

    act(() => result.current.reload());
    await waitFor(() => expect(result.current.state).toEqual({ status: "error", message: "blip", data: [1] }));

    act(() => result.current.reload());
    await waitFor(() => expect(result.current.state).toEqual({ status: "ready", data: [3] }));
  });
});
