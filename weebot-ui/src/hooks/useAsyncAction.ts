"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** idle -> pending -> done | error, as a discriminated union like `Remote<T>`. */
export type AsyncState =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "done" }
  | { status: "error"; error: string };

/**
 * One in-flight run of an async action (approve, interrupt, delete...). `run` returns true when
 * the action finished and false when it failed or was refused. It never throws, so an onClick
 * can call it directly. The re-entry guard is a ref: a state flag alone lets a second click in
 * the same tick through, before the re-render that would disable the button.
 */
export function useAsyncAction<A extends unknown[]>(action: (...args: A) => unknown | Promise<unknown>) {
  const [state, setState] = useState<AsyncState>({ status: "idle" });
  const inFlight = useRef(false);
  const latest = useRef(action);
  useEffect(() => {
    latest.current = action;
  });

  const run = useCallback(async (...args: A): Promise<boolean> => {
    if (inFlight.current) return false;
    inFlight.current = true;
    setState({ status: "pending" });
    try {
      await latest.current(...args);
      setState({ status: "done" });
      return true;
    } catch (e) {
      setState({ status: "error", error: e instanceof Error ? e.message : String(e) });
      return false;
    } finally {
      inFlight.current = false;
    }
  }, []);

  const reset = useCallback(() => setState({ status: "idle" }), []);

  return { state, run, reset, pending: state.status === "pending" };
}
