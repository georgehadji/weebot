"use client";

import { useSyncExternalStore } from "react";

function subscribe(notify: () => void): () => void {
  document.addEventListener("visibilitychange", notify);
  return () => document.removeEventListener("visibilitychange", notify);
}

/** False while the tab is hidden; pollers pause on it. The server render assumes visible. */
export function usePageVisible(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => document.visibilityState !== "hidden",
    () => true
  );
}
