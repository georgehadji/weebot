"use client";

import { useDeferredValue, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus, Search, X } from "lucide-react";
import { StateView } from "@/components/common/StateView";
import { StatusBadge } from "@/components/common/StatusBadge";
import { cn } from "@/lib/utils";
import { useSessionList } from "@/hooks/useSessionList";
import { filterSessions } from "@/lib/sessions";
import { Session } from "@/types/events";

function isActive(status: string): boolean {
  return status === "running" || status === "waiting";
}

export function SessionRail() {
  const { state, reload } = useSessionList();
  const pathname = usePathname();
  const [query, setQuery] = useState("");
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
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions…"
            className="h-8 w-full rounded-md border border-input bg-background pl-7 pr-7 text-xs placeholder:text-muted-foreground focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring [&::-webkit-search-cancel-button]:hidden"
            aria-label="Search sessions"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-1.5 py-2">
        <StateView
          state={state}
          loadingLabel="Loading sessions"
          errorTitle="Couldn't load sessions"
          onRetry={reload}
          isEmpty={(sessions) => sessions.length === 0}
          empty={
            <p className="px-2 py-4 text-xs text-muted-foreground">
              No sessions yet. Start one with <span className="font-medium">New</span>.
            </p>
          }
        >
          {(sessions) => <SessionGroups sessions={sessions} query={deferredQuery} pathname={pathname} />}
        </StateView>
      </div>

      <div className="border-t p-2">
        <Link
          href="/"
          className="flex h-9 w-full items-center justify-center gap-1.5 rounded-md pointer-coarse:h-11 bg-agent text-xs font-medium text-agent-foreground transition-colors hover:bg-agent/90"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          New
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
  if (sessions.length === 0) return null;
  return (
    <div className="mb-2">
      <p className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      {sessions.map((s) => {
        const href = `/sessions/${s.id}`;
        return (
          <Link
            key={s.id}
            href={href}
            aria-current={pathname === href ? "page" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-md px-2 py-2 text-xs transition-colors pointer-coarse:py-3",
              pathname === href
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
            )}
          >
            <StatusBadge status={s.status} variant="icon" />
            <span className="truncate">{s.title || "New session"}</span>
          </Link>
        );
      })}
    </div>
  );
}
