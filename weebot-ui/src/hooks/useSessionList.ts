"use client";

/**
 * useSessionList — session rail data, WS-driven instead of polled.
 *
 * Replaces the old sessions page's `setInterval(loadSessions, 5000)`.
 * One REST fetch seeds the list; every status change after that arrives
 * via SessionPresenceEvent over the always-on global connection (T1.6),
 * patched into the same array in place.
 */

import { useEffect, useMemo, useRef } from "react";
import { api } from "@/lib/api";
import { useRemote } from "./useRemote";
import { useSessionPresence } from "./useSessionPresence";
import { Session, SessionPresenceEvent } from "@/types/events";
import { Remote, remoteData } from "@/types/remote";

export function applyPresence(session: Session, update?: SessionPresenceEvent): Session {
  if (!update) return session;
  const title = update.title || session.title;
  if (session.status === update.status && session.title === title) return session;
  return { ...session, status: update.status as Session["status"], title };
}

const loadSessions = () => api.sessions.list({ limit: "100" }).then((data) => data.sessions);

export function useSessionList() {
  const { state, reload } = useRemote(loadSessions);
  const presence = useSessionPresence();
  const sessions = remoteData(state);

  // Presence deltas are applied at read time rather than copied into
  // `sessions`, so an update that lands before the REST seed isn't lost.
  // A "deleted" frame (the delete route sends one, D10) removes the row.
  const liveSessions = useMemo(
    () =>
      sessions && presence.size > 0
        ? sessions
            .filter((s) => presence.get(s.id)?.status !== "deleted")
            .map((s) => applyPresence(s, presence.get(s.id)))
        : sessions,
    [sessions, presence]
  );

  // Presence only patches sessions already in the list, so a session created after the seed
  // never showed in the rail until a reload. An id the list lacks triggers one reload.
  const asked = useRef(new Set<string>());
  useEffect(() => {
    if (!sessions) return;
    const known = new Set(sessions.map((s) => s.id));
    for (const [id, update] of presence) {
      if (update.status === "deleted") continue;
      if (!known.has(id) && !asked.current.has(id)) {
        asked.current.add(id);
        reload();
        return;
      }
    }
  }, [sessions, presence, reload]);

  const live = useMemo<Remote<Session[]>>(() => {
    if (state.status === "ready") return { status: "ready", data: liveSessions ?? state.data };
    if (state.status === "error") return { ...state, data: liveSessions };
    return state;
  }, [state, liveSessions]);

  return { state: live, sessions: liveSessions ?? [], reload };
}
