"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { ConsoleShell } from "@/components/shell/ConsoleShell";
import { ConversationPane } from "@/components/conversation/ConversationPane";
import { MissionDock } from "@/components/dock/Dock";
import { SessionLifecycleStatus } from "@/components/conversation/Composer";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { useSessionPresence } from "@/hooks/useSessionPresence";
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
  const [session, setSession] = useState<Session | null>(null);
  const [initialEvents, setInitialEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const { isConnected } = useSessionEvents(sessionId);
  const presence = useSessionPresence();

  useEffect(() => {
    const update = presence.get(sessionId);
    if (!update) return;
    setSession((current) =>
      current
        ? {
            ...current,
            status: update.status as Session["status"],
            title: update.title || current.title,
          }
        : current
    );
  }, [presence, sessionId]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await api.sessions.get(sessionId);
        if (cancelled) return;
        setSession(data);
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

  if (loading) {
    return (
      <ConsoleShell isConnected={isConnected}>
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </ConsoleShell>
    );
  }

  if (!session) {
    return (
      <ConsoleShell isConnected={isConnected}>
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Session not found.
        </div>
      </ConsoleShell>
    );
  }

  return (
    <ConsoleShell
      title={session.title || "Untitled session"}
      isConnected={isConnected}
      dock={<MissionDock sessionId={sessionId} />}
    >
      <ConversationPane
        sessionId={sessionId}
        status={toLifecycleStatus(session.status)}
        initialEvents={initialEvents}
        onSessionCreated={(id) => router.push(`/sessions/${id}`)}
      />
    </ConsoleShell>
  );
}
