"use client";

import { useState } from "react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { StateView } from "@/components/common/StateView";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRemote } from "@/hooks/useRemote";
import { api } from "@/lib/api";
import { useToast } from "@/providers/ToastProvider";
import { Session } from "@/types/events";

const loadSessions = () => api.sessions.list({ limit: "100" }).then((data) => data.sessions);

function eventsLabel(count: number): string {
  return `${count} ${count === 1 ? "event" : "events"}`;
}

export default function SessionsPage() {
  const { state, reload } = useRemote(loadSessions, 5000);
  const [pendingDelete, setPendingDelete] = useState<Session | null>(null);
  const { toast } = useToast();

  const deleteSession = async (session: Session) => {
    try {
      await api.sessions.delete(session.id);
      reload();
    } catch (err) {
      toast({
        title: "Failed to delete session",
        description: err instanceof Error ? err.message : undefined,
        variant: "error",
      });
    }
  };

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-3xl font-bold">Sessions</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={reload} aria-label="Refresh sessions">
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Link href="/" className={buttonVariants()}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            New session
          </Link>
        </div>
      </div>

      <StateView
        state={state}
        loadingLabel="Loading sessions"
        errorTitle="Couldn't load sessions"
        onRetry={reload}
        isEmpty={(sessions) => sessions.length === 0}
        empty={
          <Card>
            <CardContent className="flex h-64 flex-col items-center justify-center text-muted-foreground">
              <p className="mb-4">No sessions yet</p>
              <Link href="/" className={buttonVariants()}>
                Create your first session
              </Link>
            </CardContent>
          </Card>
        }
      >
        {(sessions) => (
          <ul className="space-y-4">
            {sessions.map((session) => (
              <li key={session.id}>
                <Card className="transition-colors hover:border-primary/50">
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <CardTitle className="text-lg">
                          <Link
                            href={`/sessions/${session.id}`}
                            className="transition-colors hover:text-primary"
                          >
                            {session.title || "New session"}
                          </Link>
                        </CardTitle>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {formatDistanceToNow(new Date(session.created_at), { addSuffix: true })}
                          {" · "}
                          {eventsLabel(session.event_count)}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <StatusBadge status={session.status} />
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Delete session ${session.title || session.id}`}
                          className="text-status-error-fg hover:text-status-error-fg/80"
                          onClick={() => setPendingDelete(session)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </CardHeader>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </StateView>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title="Delete this session?"
        description={
          <>
            &ldquo;{pendingDelete?.title || "New session"}&rdquo; and its history will be removed. This cannot be
            undone.
          </>
        }
        confirmLabel="Delete session"
        destructive
        onConfirm={() => pendingDelete && deleteSession(pendingDelete)}
      />
    </div>
  );
}
