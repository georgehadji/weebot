"use client";

import { useDeferredValue, useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus, Search, X } from "lucide-react";
import { StateView } from "@/components/common/StateView";
import { StatusBadge } from "@/components/common/StatusBadge";
import { cn } from "@/lib/utils";
import { useSessionList } from "@/hooks/useSessionList";
import { useUrlState } from "@/hooks/useUrlState";
import { filterSessions, modelsLabel } from "@/lib/sessions";
import { Session } from "@/types/events";

function isActive(status: string): boolean {
  return status === "running" || status === "waiting";
}

const SEARCH_DEBOUNCE_MS = 250;

/**
 * The rail search as `?q=`. The input keeps its own text so typing never waits on the router;
 * the URL follows after a pause (one `replace`, not one per key), and a change that did not come
 * from here (back/forward, a shared link) is copied into the input.
 */
function useSearchQuery(): [string, (next: string) => void] {
  const [urlQuery, setUrlQuery] = useUrlState("q", "");
  const [query, setQuery] = useState(urlQuery);
  const written = useRef(urlQuery);

  useEffect(() => {
    if (urlQuery === written.current) return;
    written.current = urlQuery;
    setQuery(urlQuery);
  }, [urlQuery]);

  useEffect(() => {
    if (query === written.current) return;
    const timer = setTimeout(() => {
      written.current = query;
      setUrlQuery(query);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, setUrlQuery]);

  return [query, setQuery];
}

export function SessionRail() {
  const { state, reload } = useSessionList();
  const pathname = usePathname();
  const [query, setQuery] = useSearchQuery();
  const deferredQuery = useDeferredValue(query);

  return (
    <nav aria-label="Sessions" className="flex h-full w-rail shrink-0 flex-col border-r bg-surface-1">
      <div className="flex items-center gap-2 border-b p-2.5">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            name="q"
            autoComplete="off"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions…"
            className="focus-ring h-8 w-full rounded-md border border-input bg-background pl-7 pr-7 text-xs placeholder:text-muted-foreground pointer-coarse:h-11 pointer-coarse:pr-11 [&::-webkit-search-cancel-button]:hidden"
            aria-label="Search sessions"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="focus-ring absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground hover:text-foreground pointer-coarse:right-0 pointer-coarse:h-11 pointer-coarse:w-11"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overscroll-contain px-1.5 py-2">
        <StateView
          state={state}
          loadingLabel="Loading sessions"
          errorTitle="Couldn't load sessions"
          onRetry={reload}
          isEmpty={(sessions) => sessions.length === 0}
          empty={
            <p className="px-2 py-4 text-xs text-muted-foreground">
              No sessions yet. Start one with <span className="font-medium">New Session</span>.
            </p>
          }
        >
          {(sessions) => <SessionGroups sessions={sessions} query={deferredQuery} pathname={pathname} />}
        </StateView>
      </div>

      <div className="border-t p-2">
        <Link
          href="/"
          className="focus-ring flex h-9 w-full items-center justify-center gap-1.5 rounded-md pointer-coarse:h-11 bg-agent text-xs font-medium text-agent-foreground transition-colors hover:bg-agent/90"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          New Session
        </Link>
      </div>
    </nav>
  );
}

function SessionGroups({
  sessions,
  query,
  pathname,
}: {
  sessions: Session[];
  query: string;
  pathname: string | null;
}) {
  const matches = useMemo(() => filterSessions(sessions, query), [sessions, query]);
  if (matches.length === 0) {
    return (
      <p className="px-2 py-4 text-xs text-muted-foreground" role="status">
        No sessions match &ldquo;{query.trim()}&rdquo;.
      </p>
    );
  }
  return (
    <>
      <SessionGroup label="Active" sessions={matches.filter((s) => isActive(s.status))} pathname={pathname} />
      <SessionGroup label="Recent" sessions={matches.filter((s) => !isActive(s.status))} pathname={pathname} />
    </>
  );
}

function SessionGroup({
  label,
  sessions,
  pathname,
}: {
  label: string;
  sessions: Session[];
  pathname: string | null;
}) {
  const headingId = useId();
  if (sessions.length === 0) return null;
  return (
    <section className="mb-2" aria-labelledby={headingId}>
      <h2 id={headingId} className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </h2>
      {/* A flex column (margins do not collapse) so each row's -m-1/p-1 ring room nets to zero. */}
      <ul className="flex flex-col">
        {sessions.map((s) => {
          const href = `/sessions/${s.id}`;
          const models = modelsLabel(s.models);
          return (
            <li key={s.id} className="cv-auto -m-1 p-1">
              <Link
                href={href}
                aria-current={pathname === href ? "page" : undefined}
                className={cn(
                  "focus-ring flex items-center gap-2 rounded-md px-2 py-2 text-xs transition-colors pointer-coarse:py-3",
                  pathname === href
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                )}
              >
                <StatusBadge status={s.status} variant="icon" />
                <span className="min-w-0">
                  <span className="block truncate" title={s.title || undefined}>
                    {s.title || "New session"}
                  </span>
                  {models && (
                    <span translate="no" title={models} className="block truncate font-mono">
                      {models}
                    </span>
                  )}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
