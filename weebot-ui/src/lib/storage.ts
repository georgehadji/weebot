/**
 * Safe browser storage. An Adapter over `localStorage` / `sessionStorage` that never throws:
 * privacy mode, a blocked-cookies setting or a full quota make the real API throw, and a lost
 * preference is never worth an error. Writes notify this tab's subscribers (the `storage` event
 * only fires in other tabs), so `useStoredValue` can read it with `useSyncExternalStore`.
 *
 * Direct `localStorage` / `sessionStorage` use anywhere else in `src` is a lint error.
 */

export type StorageArea = "local" | "session";

export const STORAGE_KEYS = {
  theme: "weebot_theme",
  backendUrl: "weebot_backend_url",
  wsUrl: "weebot_ws_url",
  apiKey: "weebot_api_key",
  executionMode: "weebot_execution_mode",
} as const;

export const draftKey = (sessionId: string | null) => `weebot_draft:${sessionId ?? "new"}`;

function area(which: StorageArea): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return which === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

const listeners = new Map<string, Set<() => void>>();
const slot = (which: StorageArea, key: string) => `${which}:${key}`;

export function readStored(which: StorageArea, key: string): string | null {
  try {
    return area(which)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

/** `null` removes the key. Returns whether the browser accepted the write. */
export function writeStored(which: StorageArea, key: string, value: string | null): boolean {
  let ok = true;
  try {
    const store = area(which);
    if (!store) ok = false;
    else if (value === null) store.removeItem(key);
    else store.setItem(key, value);
  } catch {
    ok = false;
  }
  listeners.get(slot(which, key))?.forEach((listener) => listener());
  return ok;
}

export function subscribeStored(which: StorageArea, key: string, listener: () => void): () => void {
  const id = slot(which, key);
  const set = listeners.get(id) ?? new Set<() => void>();
  set.add(listener);
  listeners.set(id, set);
  const onStorage = (event: StorageEvent) => {
    if (event.key === key || event.key === null) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    set.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}
