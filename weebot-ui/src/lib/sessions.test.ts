import { describe, expect, it } from "vitest";
import { filterSessions, normalizeForSearch } from "./sessions";
import { Session } from "@/types/events";

const session = (id: string, title: string | undefined, prompt = ""): Session => ({
  id,
  user_id: "u",
  agent_id: "a",
  status: "completed",
  title,
  context: { last_prompt: prompt },
  created_at: "2026-10-20T00:00:00Z",
  updated_at: "2026-10-20T00:00:00Z",
  event_count: 0,
});

const all = [
  session("1", "Weather at Γιαννιτσά tomorrow?"),
  session("2", "Refactor billing", "use the new tax API"),
  session("3", undefined, "Café menu translation"),
];

describe("normalizeForSearch", () => {
  it("ignores case, accents and the final sigma", () => {
    expect(normalizeForSearch("ΓΙΑΝΝΙΤΣΑ")).toBe(normalizeForSearch("Γιαννιτσά"));
    expect(normalizeForSearch("Café")).toBe("cafe");
    expect(normalizeForSearch("ΟΔΟΣ")).toBe(normalizeForSearch("οδός"));
  });
});

describe("filterSessions", () => {
  it("returns everything for an empty or blank query", () => {
    expect(filterSessions(all, "")).toBe(all);
    expect(filterSessions(all, "   ")).toBe(all);
  });

  it("matches Greek regardless of case and tonos", () => {
    expect(filterSessions(all, "γιαννιτσα").map((s) => s.id)).toEqual(["1"]);
    expect(filterSessions(all, "ΓΙΑΝΝΙΤΣΑ").map((s) => s.id)).toEqual(["1"]);
  });

  it("looks at the prompt when there is no title", () => {
    expect(filterSessions(all, "cafe").map((s) => s.id)).toEqual(["3"]);
  });

  it("requires every word, in any order", () => {
    expect(filterSessions(all, "tax billing").map((s) => s.id)).toEqual(["2"]);
    expect(filterSessions(all, "tax weather")).toEqual([]);
  });
});
