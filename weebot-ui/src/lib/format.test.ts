import { describe, expect, it } from "vitest";
import {
  DEFAULT_INTL,
  formatCurrency,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRelative,
  formatTime,
  formatterCacheSize,
  parseIso,
  plural,
} from "./format";

const de = { locale: "de-DE", timeZone: "Europe/Berlin" };

describe("lib/format", () => {
  it("builds each formatter once (Flyweight cache)", () => {
    formatNumber(1234.5, DEFAULT_INTL);
    const size = formatterCacheSize();
    formatNumber(99, DEFAULT_INTL);
    expect(formatterCacheSize()).toBe(size);
  });

  it("formats numbers and currency per locale", () => {
    expect(formatNumber(1234567, DEFAULT_INTL)).toBe("1,234,567");
    expect(formatNumber(1234567, de)).toBe("1.234.567");
    expect(formatCurrency(6, DEFAULT_INTL)).toBe("$6.00");
    expect(formatCurrency(0.00123, DEFAULT_INTL, { precision: 4 })).toBe("$0.0012");
  });

  it("clamps and rounds a percentage", () => {
    expect(formatPercent(42.4)).toBe("42%");
    expect(formatPercent(180)).toBe("100%");
    expect(formatPercent(-5)).toBe("0%");
    expect(formatPercent(Number.NaN)).toBe("0%");
  });

  it("returns null for an invalid date instead of 'Invalid Date'", () => {
    expect(formatDateTime("not a date")).toBeNull();
    expect(formatTime("")).toBeNull();
    expect(formatTime(undefined)).toBeNull();
    expect(formatRelative("nope")).toBeNull();
  });

  it("reads a naive backend timestamp as UTC, not local time", () => {
    expect(parseIso("2026-11-03T10:00:00")?.toISOString()).toBe("2026-11-03T10:00:00.000Z");
    expect(parseIso("2026-11-03T10:00:00+02:00")?.toISOString()).toBe("2026-11-03T08:00:00.000Z");
  });

  it("formats in the reader's time zone", () => {
    expect(formatTime("2026-11-03T10:00:00Z", DEFAULT_INTL)).toMatch(/10:00:00/);
    expect(formatTime("2026-11-03T10:00:00Z", de)).toMatch(/11:00:00/);
  });

  it("formats relative time against an injected clock", () => {
    const now = Date.parse("2026-11-03T10:00:00Z");
    expect(formatRelative("2026-11-03T09:55:00Z", DEFAULT_INTL, now)).toBe("5 minutes ago");
    expect(formatRelative("2026-11-03T12:00:00Z", DEFAULT_INTL, now)).toBe("in 2 hours");
  });

  it("picks the plural form", () => {
    const forms = { one: "{n} model", other: "{n} models" };
    expect(plural(1, DEFAULT_INTL, forms)).toBe("1 model");
    expect(plural(0, DEFAULT_INTL, forms)).toBe("0 models");
    expect(plural(1200, DEFAULT_INTL, forms)).toBe("1,200 models");
  });
});
