"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { ConversationPane } from "@/components/conversation/ConversationPane";
import { SessionLifecycleStatus } from "@/components/conversation/Composer";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { useShellSlots } from "@/hooks/useShellSlots";
import { useSessionPresence } from "@/hooks/useSessionPresence";
import { applyPresence } from "@/hooks/useSessionList";
import { api } from "@/lib/api";
import { AgentEvent, Session } from "@/types/events";

// SessionStatus and SessionLifecycleStatus share the same vocabulary
// (both mirror the backend's weebot.domain.models.session.SessionStatus).
function toLifecycleStatus(status: Session["status"]): SessionLifecycleStatus {
  return status;
}

export default function SessionPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.id as string;
  const [loadedSession, setLoadedSession] = useState<Session | null>(null);
  const [initialEvents, setInitialEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const { isConnected } = useSessionEvents(sessionId);
  const presence = useSessionPresence();
  // Applied at read time, so a status change that arrives before the REST
  // load finishes still shows once the session is in.
  const session = loadedSession && applyPresence(loadedSession, presence.get(sessionId));

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await api.sessions.get(sessionId);
        if (cancelled) return;
        setLoadedSession(data);
        const events = await api.sessions.events(sessionId);
        if (!cancelled) setInitialEvents(events);
      } catch (e) {
        console.error("Failed to load session:", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useShellSlots({
    title: loading ? "Loading session" : session ? session.title || "New session" : "Session not found",
    isConnected,
    dockSessionId: session ? sessionId : null,
  });

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Loading session" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        Session not found.
      </div>
    );
  }

  return (
    <ConversationPane
      key={sessionId}
      sessionId={sessionId}
      status={toLifecycleStatus(session.status)}
      initialEvents={initialEvents}
      onSessionCreated={(id) => router.push(`/sessions/${id}`)}
    />
  );
}
