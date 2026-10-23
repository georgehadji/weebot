"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useSessionList } from "@/hooks/useSessionList";
import { Session } from "@/types/events";

const STATUS_DOT: Record<string, string> = {
  running: "bg-status-live",
  waiting: "bg-status-waiting",
  pending: "bg-status-idle",
  completed: "bg-status-idle",
  failed: "bg-status-error",
};

function isActive(status: string): boolean {
  return status === "running" || status === "waiting";
}

export function SessionRail() {
  const { sessions, loading, error, refresh } = useSessionList();
  const pathname = usePathname();
  const [query, setQuery] = useState("");

  const filteredSessions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return sessions;
    return sessions.filter((session) => (session.title || "Untitled session").toLocaleLowerCase().includes(normalized));
  }, [query, sessions]);

  const active = filteredSessions.filter((s) => isActive(s.status));
  const recent = filteredSessions.filter((s) => !isActive(s.status));

  return (
    <aside className="flex h-full w-rail shrink-0 flex-col border-r bg-surface-1">
      <div className="flex items-center gap-2 border-b p-2.5">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setQuery("");
            }}
            placeholder="Search sessions…"
            className="h-8 w-full rounded-md border border-input bg-background pl-7 pr-7 text-xs placeholder:text-muted-foreground focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
            aria-label="Search sessions"
          />
          {query && (
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="absolute right-1 top-1"
              onClick={() => setQuery("")}
              aria-label="Clear session search"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-1.5 py-2">
        {loading ? (
          <p className="px-2 py-4 text-xs text-muted-foreground">Loading…</p>
        ) : error ? (
          <div className="px-2 py-4 text-xs">
            <p className="text-status-error">Couldn&apos;t load sessions.</p>
            <Button variant="link" size="sm" className="mt-1 h-auto px-0" onClick={() => void refresh()}>
              Try again
            </Button>
          </div>
        ) : (
          <>
            <SessionGroup label="Active" sessions={active} pathname={pathname} />
            <SessionGroup label="Recent" sessions={recent} pathname={pathname} />
            {sessions.length === 0 && (
              <p className="px-2 py-4 text-xs text-muted-foreground">No sessions yet.</p>
            )}
            {sessions.length > 0 && filteredSessions.length === 0 && (
              <p className="px-2 py-4 text-xs text-muted-foreground">No sessions match “{query}”.</p>
            )}
          </>
        )}
      </div>

      <div className="border-t p-2">
        <Link
          href="/"
          className="flex h-8 w-full items-center justify-center gap-1.5 rounded-md bg-agent text-xs font-medium text-agent-foreground hover:bg-agent/90 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          New
        </Link>
      </div>
    </aside>
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
      <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {sessions.map((s) => {
        const href = `/sessions/${s.id}`;
        return (
          <Link
            key={s.id}
            href={href}
            className={cn(
              "flex items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors",
              pathname === href
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
            )}
          >
            <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", STATUS_DOT[s.status] ?? "bg-status-idle")} />
            <span className="truncate">{s.title || "Untitled session"}</span>
          </Link>
        );
      })}
    </div>
  );
}
