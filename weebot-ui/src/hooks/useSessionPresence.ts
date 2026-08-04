"use client";

/**
 * useSessionPresence — live session status deltas for the session rail.
 *
 * Replaces polling `/api/sessions` on an interval: a single always-on
 * global connection (see EventStreamProvider) delivers a
 * SessionPresenceEvent whenever any session's status transitions.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { SessionPresenceEvent } from "@/types/events";
import { useEventStreamContext } from "@/providers/EventStreamProvider";

export function useSessionPresence(): Map<string, SessionPresenceEvent> {
  const { subscribePresence } = useEventStreamContext();
  const presenceRef = useRef<Map<string, SessionPresenceEvent>>(new Map());
  const [, forceRender] = useState(0);

  const onPresence = useCallback((event: SessionPresenceEvent) => {
    presenceRef.current = new Map(presenceRef.current).set(event.about_session_id, event);
    forceRender((n) => n + 1);
  }, []);

  useEffect(() => subscribePresence(onPresence), [subscribePresence, onPresence]);

  return presenceRef.current;
}
