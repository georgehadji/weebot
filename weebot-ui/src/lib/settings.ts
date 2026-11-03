/**
 * Connection settings (Repository): where the backend lives and which API key to send. One owner
 * for what `lib/api.ts`, `ConnectionStatus`, `EventStreamProvider` and the ops page each used to
 * parse out of storage on their own.
 *
 * The URLs live in localStorage (they outlive the tab); the API key lives in sessionStorage so it
 * is gone when the tab closes.
 */

import { readStored, STORAGE_KEYS, writeStored } from "@/lib/storage";

const trimmed = (value: string | null) => value?.trim() || null;

/** The configured backend origin without a trailing slash, or null for same-origin. */
export function backendUrl(): string | null {
  const configured = trimmed(readStored("local", STORAGE_KEYS.backendUrl));
  return configured ? configured.replace(/\/$/, "") : null;
}

/** The configured WebSocket URL, or null when none was set. */
export function wsUrl(): string | null {
  return trimmed(readStored("local", STORAGE_KEYS.wsUrl));
}

/** `/api` for same-origin, otherwise `<backend>/api`. */
export function apiBase(): string {
  const base = backendUrl();
  return base ? `${base}/api` : "/api";
}

export function apiKey(): string | null {
  return readStored("session", STORAGE_KEYS.apiKey);
}

/** An empty or blank key clears it. */
export function setApiKey(key: string | null): void {
  writeStored("session", STORAGE_KEYS.apiKey, trimmed(key));
}

export function setConnection({ backendUrl: backend, wsUrl: ws }: { backendUrl: string; wsUrl: string }): void {
  writeStored("local", STORAGE_KEYS.backendUrl, trimmed(backend));
  writeStored("local", STORAGE_KEYS.wsUrl, trimmed(ws));
}
