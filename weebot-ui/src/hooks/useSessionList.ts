"use client";

/**
 * useSessionList — session rail data, WS-driven instead of polled.
 *
 * Replaces the old sessions page's `setInterval(loadSessions, 5000)`.
 * One REST fetch seeds the list; every status change after that arrives
 * via SessionPresenceEvent over the always-on global connection (T1.6),
 * patched into the same array in place.
 */

import { useMemo } from "react";
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
  const liveSessions = useMemo(
    () =>
      sessions && presence.size > 0 ? sessions.map((s) => applyPresence(s, presence.get(s.id))) : sessions,
    [sessions, presence]
  );

  const live = useMemo<Remote<Session[]>>(() => {
    if (state.status === "ready") return { status: "ready", data: liveSessions ?? state.data };
    if (state.status === "error") return { ...state, data: liveSessions };
    return state;
  }, [state, liveSessions]);

  return { state: live, sessions: liveSessions ?? [], reload };
}
