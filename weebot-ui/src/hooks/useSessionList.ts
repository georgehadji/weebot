"use client";

/**
 * useSessionList — session rail data, WS-driven instead of polled.
 *
 * Replaces the old sessions page's `setInterval(loadSessions, 5000)`.
 * One REST fetch seeds the list; every status change after that arrives
 * via SessionPresenceEvent over the always-on global connection (T1.6),
 * patched into the same array in place.
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSessionPresence } from "./useSessionPresence";
import { Session } from "@/types/events";

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

  useEffect(() => {
    if (presence.size === 0) return;
    setSessions((prev) => {
      let changed = false;
      const next = prev.map((s) => {
        const update = presence.get(s.id);
        if (!update) return s;
        if (s.status === update.status && s.title === (update.title || s.title)) return s;
        changed = true;
        return { ...s, status: update.status as Session["status"], title: update.title || s.title };
      });
      return changed ? next : prev;
    });
  }, [presence]);

  return { sessions, loading, error };
}
