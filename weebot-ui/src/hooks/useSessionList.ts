"use client";

/**
 * useSessionList — session rail data, WS-driven instead of polled.
 *
 * Replaces the old sessions page's `setInterval(loadSessions, 5000)`.
 * One REST fetch seeds the list; every status change after that arrives
 * via SessionPresenceEvent over the always-on global connection (T1.6),
 * patched into the same array in place.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useSessionPresence } from "./useSessionPresence";
import { Session, SessionPresenceEvent } from "@/types/events";

export function applyPresence(session: Session, update?: SessionPresenceEvent): Session {
  if (!update) return session;
  const title = update.title || session.title;
  if (session.status === update.status && session.title === title) return session;
  return { ...session, status: update.status as Session["status"], title };
}

export function useSessionList() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const presence = useSessionPresence();

  useEffect(() => {
    let cancelled = false;
    api.sessions
      .list({ limit: "100" })
      .then((data) => {
        if (!cancelled) {
          setSessions(data.sessions);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load sessions");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Presence deltas are applied at read time rather than copied into
  // `sessions`, so an update that lands before the REST seed isn't lost.
  const liveSessions = useMemo(
    () => (presence.size === 0 ? sessions : sessions.map((s) => applyPresence(s, presence.get(s.id)))),
    [sessions, presence]
  );

  return { sessions: liveSessions, loading, error };
}
