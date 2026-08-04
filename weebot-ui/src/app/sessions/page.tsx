"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { Plus, RefreshCw, Trash2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api } from "@/lib/api";
import { Session } from "@/types/events";
import { useToast } from "@/providers/ToastProvider";

// Matches weebot.domain.models.session.SessionStatus.value exactly —
// the previous 'active'/'cancelled'/'error' cases never matched a real
// backend value (the API returns pending/running/waiting/completed/failed),
// so every session silently fell through to the gray default.
function getStatusColor(status: string) {
  switch (status) {
    case "running":
      return "bg-status-live";
    case "waiting":
      return "bg-status-waiting";
    case "completed":
      return "bg-status-idle";
    case "failed":
      return "bg-status-error";
    default:
      return "bg-status-idle";
  }
}

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  const loadSessions = async () => {
    try {
      setLoading(true);
      const data = await api.sessions.list({ limit: "100" });
      setSessions(data.sessions);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSessions();
    // Refresh every 5 seconds
    const interval = setInterval(loadSessions, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to delete this session?")) return;
    try {
      await api.sessions.delete(id);
      loadSessions();
    } catch {
      toast({ title: "Failed to delete session", variant: "error" });
    }
  };

  if (loading && sessions.length === 0) {
    return (
      <div className="container mx-auto py-8 px-4">
        <div className="flex items-center justify-center h-64">
          <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Sessions</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={loadSessions} aria-label="Refresh sessions">
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Link href="/">
            <Button>
              <Plus className="h-4 w-4 mr-1" />
              New Session
            </Button>
          </Link>
        </div>
      </div>

      {error && (
        <div className="surface-error flex flex-col gap-2 mb-4 p-4 rounded-lg border">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5" />
            <span className="font-medium">Connection Error</span>
          </div>
          <p className="text-sm">{error}</p>
          <p className="text-xs text-red-400">
            Make sure the backend is running: python -m weebot.interfaces.web.main
          </p>
        </div>
      )}

      <ScrollArea className="h-[600px]">
        <div className="space-y-4">
          {sessions.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center h-64 text-muted-foreground">
                <p className="mb-4">No sessions yet</p>
                <Link href="/">
                  <Button>Create your first session</Button>
                </Link>
              </CardContent>
            </Card>
          ) : (
            sessions.map((session) => (
              <Card key={session.id} className="hover:border-primary/50 transition-colors">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-3 h-3 rounded-full ${getStatusColor(session.status)}`} />
                      <div>
                        <CardTitle className="text-lg">
                          <Link
                            href={`/sessions/${session.id}`}
                            className="hover:text-primary transition-colors"
                          >
                            {session.title || "Untitled Session"}
                          </Link>
                        </CardTitle>
                        <p className="text-sm text-muted-foreground mt-1">
                          {formatDistanceToNow(new Date(session.created_at), {
                            addSuffix: true,
                          })}
                          {" · "}
                          {session.event_count} events
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={session.status === "running" ? "default" : "secondary"}>
                        {session.status}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete session ${session.title || session.id}`}
                        className="text-status-error hover:text-status-error/80"
                        onClick={() => handleDelete(session.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
              </Card>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
