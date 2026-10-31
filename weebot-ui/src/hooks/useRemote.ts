"use client";

import { useCallback, useEffect, useState } from "react";
import { Remote } from "@/types/remote";

/**
 * Load data into a `Remote<T>`, optionally refreshing on an interval.
 *
 * `load` must be stable (module-level or `useCallback`): a new function restarts the load.
 * A failed refresh keeps the last good data (`error` carries it); `reload()` retries now.
 */
export function useRemote<T>(load: () => Promise<T>, pollMs?: number) {
  const [state, setState] = useState<Remote<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let started = 0;
    let applied = 0; // a response older than one already shown is dropped: the newest wins
    const run = () => {
      const id = ++started;
      return load().then(
        (data) => {
          if (cancelled || id < applied) return;
          applied = id;
          setState({ status: "ready", data });
        },
        (err: unknown) => {
          if (cancelled || id < applied) return;
          applied = id;
          const message = err instanceof Error ? err.message : "Something went wrong";
          setState((prev) => ({
            status: "error",
            message,
            data: prev.status === "ready" || prev.status === "error" ? prev.data : undefined,
          }));
        }
      );
    };
    void run();
    const timer = pollMs ? setInterval(run, pollMs) : undefined;
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [load, pollMs, attempt]);

  const reload = useCallback(() => {
    // Keep showing what we have while retrying; a first load shows the loading state again.
    setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
    setAttempt((n) => n + 1);
  }, []);

  return { state, reload };
}
