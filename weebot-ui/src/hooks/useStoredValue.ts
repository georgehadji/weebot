"use client";

import { useCallback, useSyncExternalStore } from "react";
import { readStored, StorageArea, subscribeStored, writeStored } from "@/lib/storage";

/**
 * A storage key as React state. Storage is an external store, so it is read with
 * useSyncExternalStore: no mirror-into-state effect, and hydration matches the server render
 * (which cannot see storage) because the server snapshot is `serverValue`.
 */
export function useStoredValue(
  which: StorageArea,
  key: string,
  serverValue: string | null = null
): [string | null, (next: string | null) => void] {
  const value = useSyncExternalStore(
    useCallback((notify) => subscribeStored(which, key, notify), [which, key]),
    () => readStored(which, key),
    () => serverValue
  );
  const set = useCallback((next: string | null) => void writeStored(which, key, next), [which, key]);
  return [value, set];
}
