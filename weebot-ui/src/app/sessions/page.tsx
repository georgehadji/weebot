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

function getStatusColor(status: string) {
  switch (status) {
    case "active":
      return "bg-green-500";
    case "waiting":
      return "bg-yellow-500";
    case "completed":
      return "bg-blue-500";
    case "cancelled":
      return "bg-gray-500";
    case "error":
      return "bg-red-500";
    default:
      return "bg-gray-500";
  }
}

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      alert("Failed to delete session");
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
          <Button variant="outline" size="icon" onClick={loadSessions}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Link href="/sessions/new">
            <Button>
              <Plus className="h-4 w-4 mr-1" />
              New Session
            </Button>
          </Link>
        </div>
      </div>

      {error && (
        <div className="flex flex-col gap-2 text-red-500 mb-4 p-4 bg-red-50 rounded-lg">
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
                <Link href="/sessions/new">
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
                      <Badge variant={session.status === "active" ? "default" : "secondary"}>
                        {session.status}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-red-500 hover:text-red-600"
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
