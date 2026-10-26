"use client";

import { useSyncExternalStore } from "react";

/** Tracks a CSS media query. `serverValue` is what the server render (and hydration) assumes. */
export function useMediaQuery(query: string, serverValue = false): boolean {
  return useSyncExternalStore(
    (notify) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", notify);
      return () => list.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
    () => serverValue
  );
}
