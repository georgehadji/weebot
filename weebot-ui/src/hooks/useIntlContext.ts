"use client";

import { useSyncExternalStore } from "react";
import { DEFAULT_INTL, IntlContext } from "@/lib/format";

let cached: IntlContext | null = null;

function clientSnapshot(): IntlContext {
  const locale = navigator.language || DEFAULT_INTL.locale;
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || DEFAULT_INTL.timeZone;
  // useSyncExternalStore needs the same object back while nothing changed.
  if (!cached || cached.locale !== locale || cached.timeZone !== timeZone) cached = { locale, timeZone };
  return cached;
}

function subscribe(notify: () => void): () => void {
  window.addEventListener("languagechange", notify);
  return () => window.removeEventListener("languagechange", notify);
}

/**
 * The reader's locale and time zone. The server (and the hydration pass) use en-US/UTC, then the
 * browser's values apply, so formatted text never causes a hydration mismatch and
 * `suppressHydrationWarning` is not needed.
 *
 * shortcut: a non-en-US reader sees one en-US frame at hydration; if that ever matters, send a
 * locale cookie and read it in the root layout.
 */
export function useIntlContext(): IntlContext {
  return useSyncExternalStore(subscribe, clientSnapshot, () => DEFAULT_INTL);
}
