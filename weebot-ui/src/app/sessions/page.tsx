"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { StateView } from "@/components/common/StateView";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useIntlContext } from "@/hooks/useIntlContext";
import { useRemote } from "@/hooks/useRemote";
import { api } from "@/lib/api";
import { formatRelative, plural } from "@/lib/format";
import { modelsLabel } from "@/lib/sessions";
import { Session } from "@/types/events";

const PAGE_SIZE = 100;

export default function SessionsPage() {
  // "Load More" widens the window instead of paging: the 5 s poll then refreshes everything
  // that is shown, and the backend's `offset` is not needed.
  const [limit, setLimit] = useState(PAGE_SIZE);
  const load = useCallback(() => api.sessions.list({ limit: String(limit) }), [limit]);
  const { state, reload } = useRemote(load, 5000);
  const [pendingDelete, setPendingDelete] = useState<Session | null>(null);
  const ctx = useIntlContext();

  // Throws on failure: ConfirmDialog stays open and shows the error, so the user can retry.
  const deleteSession = async (session: Session) => {
    await api.sessions.delete(session.id);
    reload();
  };

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-3xl font-bold">Sessions</h2>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={reload} aria-label="Refresh sessions">
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Link href="/" className={buttonVariants()}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            New Session
          </Link>
        </div>
      </div>

      <StateView
        state={state}
        loadingLabel="Loading sessions"
        errorTitle="Couldn't load sessions"
        onRetry={reload}
        isEmpty={({ sessions }) => sessions.length === 0}
        empty={
          <Card>
            <CardContent className="flex h-64 flex-col items-center justify-center text-muted-foreground">
              <p className="mb-4">No sessions yet</p>
              <Link href="/" className={buttonVariants()}>
                Create Your First Session
              </Link>
            </CardContent>
          </Card>
        }
      >
        {({ sessions, total }) => (
          <>
            <ul className="space-y-4">
              {sessions.map((session) => (
                <li key={session.id} className="cv-auto">
                  <Card className="transition-colors hover:border-primary/50">
                    <CardHeader className="pb-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <CardTitle className="truncate text-lg" title={session.title || undefined}>
                            <Link
                              href={`/sessions/${session.id}`}
                              className="transition-colors hover:text-primary-text"
                            >
                              {session.title || "New session"}
                            </Link>
                          </CardTitle>
                          <p className="mt-1 truncate text-sm text-muted-foreground">
                            {formatRelative(session.created_at, ctx) ?? "Unknown date"}
                            {" · "}
                            {plural(session.event_count, ctx, { one: "{n} event", other: "{n} events" })}
                            {session.models?.length ? ` · ${modelsLabel(session.models)}` : null}
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
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        </div>
                      </div>
                    </CardHeader>
                  </Card>
                </li>
              ))}
            </ul>
            {sessions.length < total && (
              <div className="mt-6 flex flex-col items-center gap-2">
                <p className="text-sm text-muted-foreground">
                  Showing {sessions.length} of {total}
                </p>
                <Button variant="outline" onClick={() => setLimit((n) => n + PAGE_SIZE)}>
                  Load More
                </Button>
              </div>
            )}
          </>
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
