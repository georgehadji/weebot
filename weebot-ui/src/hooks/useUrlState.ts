"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/** The query string with `key` set to `value`, or removed when it equals the fallback. */
export function withParam(search: string, key: string, value: string, fallback: string): string {
  const params = new URLSearchParams(search);
  if (value === fallback) params.delete(key);
  else params.set(key, value);
  return params.toString();
}

/**
 * One query parameter as state. The URL is the single source of truth, so reload, back/forward
 * and shared links all restore it, and nothing is duplicated in React state. Writes use
 * `replace`: a tab switch should not fill the history. Consumers need a Suspense boundary.
 */
export function useUrlState(key: string, fallback: string): [string, (next: string) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const value = params.get(key) ?? fallback;

  const set = useCallback(
    (next: string) => {
      // Read the live URL, not the render's params, so two writes in one tick do not drop each other.
      const qs = withParam(window.location.search, key, next, fallback);
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [key, fallback, pathname, router]
  );

  return [value, set];
}
