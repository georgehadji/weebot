/**
 * Locale-aware formatting. Pure functions over a shared cache of `Intl` formatters (Flyweight):
 * building one is expensive and they are safe to share, so each locale+options pair is built once.
 *
 * Every function takes an `IntlContext` (from `useIntlContext`) instead of reading the browser,
 * so the output is the same on the server and during hydration, and tests need no globals.
 */

export interface IntlContext {
  locale: string;
  timeZone: string;
}

/** What the server render assumes. `useIntlContext` swaps in the browser's values after hydration. */
export const DEFAULT_INTL: IntlContext = { locale: "en-US", timeZone: "UTC" };

const cache = new Map<string, unknown>();

function shared<T>(kind: string, locale: string, options: object | undefined, make: () => T): T {
  const key = `${kind}|${locale}|${options ? JSON.stringify(options) : ""}`;
  let hit = cache.get(key) as T | undefined;
  if (hit === undefined) {
    hit = make();
    cache.set(key, hit);
  }
  return hit;
}

/** Test hook: how many formatters have been built. */
export function formatterCacheSize(): number {
  return cache.size;
}

export function formatNumber(
  n: number,
  ctx: IntlContext = DEFAULT_INTL,
  options?: Intl.NumberFormatOptions
): string {
  return shared("number", ctx.locale, options, () => new Intl.NumberFormat(ctx.locale, options)).format(n);
}

/** `value` is a percentage (0-100). It is clamped and rounded to a whole percent. */
export function formatPercent(value: number, ctx: IntlContext = DEFAULT_INTL): string {
  const clamped = Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0));
  return formatNumber(Math.round(clamped) / 100, ctx, { style: "percent", maximumFractionDigits: 0 });
}

export function formatCurrency(
  n: number,
  ctx: IntlContext = DEFAULT_INTL,
  { precision = 2, currency = "USD" }: { precision?: number; currency?: string } = {}
): string {
  return formatNumber(n, ctx, {
    style: "currency",
    currency,
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
}

/**
 * The backend writes naive UTC timestamps (`2026-11-03T10:00:00`). `Date` would read those as
 * local time, so a string without a zone designator is treated as UTC. Returns null when the
 * string is not a date at all, so callers can fall back instead of printing "Invalid Date".
 */
export function parseIso(iso: string | number | Date | null | undefined): Date | null {
  if (iso === null || iso === undefined || iso === "") return null;
  let value: string | number | Date = iso;
  if (typeof value === "string" && /T\d{2}:\d{2}/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) {
    value = `${value}Z`;
  }
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function dateFormat(ctx: IntlContext, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const withZone = { ...options, timeZone: ctx.timeZone };
  return shared("date", ctx.locale, withZone, () => new Intl.DateTimeFormat(ctx.locale, withZone));
}

const DATE_TIME_STYLES = {
  short: { dateStyle: "medium", timeStyle: "short" },
  long: { dateStyle: "long", timeStyle: "medium" },
} as const satisfies Record<string, Intl.DateTimeFormatOptions>;

export function formatDateTime(
  iso: string | number | Date | null | undefined,
  ctx: IntlContext = DEFAULT_INTL,
  style: keyof typeof DATE_TIME_STYLES = "short"
): string | null {
  const d = parseIso(iso);
  return d ? dateFormat(ctx, DATE_TIME_STYLES[style]).format(d) : null;
}

export function formatDate(
  iso: string | number | Date | null | undefined,
  ctx: IntlContext = DEFAULT_INTL,
  options: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" }
): string | null {
  const d = parseIso(iso);
  return d ? dateFormat(ctx, options).format(d) : null;
}

export function formatTime(
  iso: string | number | Date | null | undefined,
  ctx: IntlContext = DEFAULT_INTL
): string | null {
  const d = parseIso(iso);
  return d ? dateFormat(ctx, { timeStyle: "medium" }).format(d) : null;
}

const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
  ["second", 1],
];

/** "5 minutes ago", "in 2 hours". `now` is injectable so tests do not depend on the clock. */
export function formatRelative(
  iso: string | number | Date | null | undefined,
  ctx: IntlContext = DEFAULT_INTL,
  now: number = Date.now()
): string | null {
  const d = parseIso(iso);
  if (!d) return null;
  const seconds = Math.round((d.getTime() - now) / 1000);
  const [unit, size] = RELATIVE_UNITS.find(([, s]) => Math.abs(seconds) >= s) ?? ["second", 1];
  const rtf = shared("relative", ctx.locale, { numeric: "auto" }, () => new Intl.RelativeTimeFormat(ctx.locale, { numeric: "auto" }));
  return rtf.format(Math.trunc(seconds / size), unit);
}

/** Picks the plural form for `n`. `{n}` in a form is replaced with the formatted number. */
export function plural(
  n: number,
  ctx: IntlContext,
  forms: Partial<Record<Intl.LDMLPluralRule, string>> & { other: string }
): string {
  const rule = shared("plural", ctx.locale, undefined, () => new Intl.PluralRules(ctx.locale)).select(n);
  return (forms[rule] ?? forms.other).replace("{n}", formatNumber(n, ctx));
}
