/**
 * Remote<T> — the state of data that comes from somewhere else.
 *
 * A discriminated union instead of separate `loading`/`error`/`data` flags, so "loading and
 * failed at once" cannot be represented. A refresh that fails keeps the last good `data`, so a
 * flaky poll shows a banner over the list instead of replacing it with an error page.
 */
export type Remote<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string; data?: T }
  | { status: "ready"; data: T };

/** The data, when there is any to show (ready, or stale behind an error). */
export function remoteData<T>(state: Remote<T>): T | undefined {
  return state.status === "ready" || state.status === "error" ? state.data : undefined;
}
