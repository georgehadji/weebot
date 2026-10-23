"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConsoleShell } from "@/components/shell/ConsoleShell";
import { ConversationPane } from "@/components/conversation/ConversationPane";
import { MissionDock } from "@/components/dock/Dock";
import { SessionLifecycleStatus } from "@/components/conversation/Composer";
import { useSessionEvents } from "@/hooks/useSessionEvents";
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
  const sessionId = params.id as string;
  const [loadedSession, setLoadedSession] = useState<Session | null>(null);
  const [initialEvents, setInitialEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const { isConnected } = useSessionEvents(sessionId);
  const presence = useSessionPresence();
  // Applied at read time, so a status change that arrives before the REST
  // load finishes still shows once the session is in.
  const session = loadedSession && applyPresence(loadedSession, presence.get(sessionId));

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const data = await api.sessions.get(sessionId);
        if (cancelled) return;
        setLoadedSession(data);
      } catch (e) {
        if (!cancelled) {
          setLoadedSession(null);
          setLoadError(e instanceof Error ? e.message : "Unable to load this session.");
          setLoading(false);
        }
        return;
      }

      try {
        const events = await api.sessions.events(sessionId);
        if (!cancelled) setInitialEvents(events);
      } catch {
        // The session remains usable if its historical event stream is
        // temporarily unavailable; live events can still reconnect.
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [sessionId, reloadKey]);

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
        <div className="mx-auto flex max-w-md flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="text-sm font-medium">Couldn&apos;t open this session</p>
          <p className="text-sm text-muted-foreground">
            {loadError || "The session may have been deleted or is no longer available."}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
              <RefreshCw className="h-3.5 w-3.5" />
              Try again
            </Button>
            <Button
              variant="ghost"
              size="sm"
              // eslint-disable-next-line @next/next/no-location-assign-relative-destination
              onClick={() => window.location.assign("/sessions")}
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              All sessions
            </Button>
          </div>
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
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        onSessionCreated={(id) => window.location.assign(`/sessions/${id}`)}
      />
    </ConsoleShell>
  );
}
