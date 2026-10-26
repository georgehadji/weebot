import { Session } from "@/types/events";

/**
 * Case-, diacritic- and final-sigma-insensitive form of *text*, so "ΓΙΑΝΝΙΤΣΑ", "Γιαννιτσά"
 * and "γιαννιτσα" all match each other (and "Cafe" matches "café").
 */
export function normalizeForSearch(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}+/gu, "")
    .toLowerCase()
    .replace(/ς/g, "σ");
}

/** What the rail search looks at: the title and the prompt the session was started with. */
function searchableText(session: Session): string {
  const ctx = session.context ?? {};
  return normalizeForSearch(
    [session.title, ctx.original_task, ctx.last_prompt].filter((v) => typeof v === "string").join(" ")
  );
}

/** Sessions whose title or prompt contains every word of *query*; all of them for an empty query. */
export function filterSessions(sessions: Session[], query: string): Session[] {
  const words = normalizeForSearch(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return sessions;
  return sessions.filter((s) => {
    const haystack = searchableText(s);
    return words.every((w) => haystack.includes(w));
  });
}
