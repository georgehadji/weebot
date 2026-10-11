"use client";

/**
 * useSessionPresence — live session status deltas for the session rail.
 *
 * Replaces polling `/api/sessions` on an interval: a single always-on
 * global connection (see EventStreamProvider) delivers a
 * SessionPresenceEvent whenever any session's status transitions.
 */

import { useCallback, useEffect, useState } from "react";
import { SessionPresenceEvent } from "@/types/events";
import { useEventStreamContext } from "@/providers/EventStreamProvider";

export function useSessionPresence(): Map<string, SessionPresenceEvent> {
  const { subscribePresence } = useEventStreamContext();
  const [presence, setPresence] = useState<Map<string, SessionPresenceEvent>>(() => new Map());

  const onPresence = useCallback((event: SessionPresenceEvent) => {
    setPresence((prev) => new Map(prev).set(event.about_session_id, event));
  }, []);

  useEffect(() => subscribePresence(onPresence), [subscribePresence, onPresence]);

  return presence;
}
