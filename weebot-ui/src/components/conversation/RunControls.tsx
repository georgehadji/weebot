"use client";

/**
 * RunControls — surfaces the already-existing (but previously unexposed)
 * cancel endpoint while a session is running. Steering text itself goes
 * through the Composer (POST /sessions/{id}/input resolves to the steer
 * strategy automatically when status === "running") — this button is for
 * "stop entirely," not "say something."
 *
 * Interrupt asks first. The backend marks a cancelled session `failed`, and Continue then sends
 * "continue" as a new task (dispatch_session_input: FAILED -> start), so it is not an undo.
 */

import { useState } from "react";
import { Square } from "lucide-react";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useToast } from "@/providers/ToastProvider";

export function RunControls({ sessionId }: { sessionId: string }) {
  const [confirming, setConfirming] = useState(false);
  const [interrupted, setInterrupted] = useState(false);
  const { toast } = useToast();

  // ConfirmDialog owns the pending guard and shows a rejection inline, so this throws a message
  // with a next step instead of the raw server text.
  const interrupt = async () => {
    try {
      await api.sessions.cancel(sessionId);
    } catch (e) {
      console.warn("[RunControls] interrupt failed", e);
      throw new Error("the interrupt did not go through. Reload the session to check its status");
    }
    setInterrupted(true);
    toast({ title: "Session interrupted", variant: "success" });
  };

  return (
    <div className="flex items-center justify-end border-t bg-surface-2 px-3 py-1.5">
      {interrupted ? (
        <span className="text-xs text-muted-foreground">Interrupted</span>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setConfirming(true)}
          className="text-status-error-fg hover:text-status-error-fg hover:bg-status-error/10"
        >
          <Square className="h-3.5 w-3.5 mr-1.5" aria-hidden="true" />
          Interrupt
        </Button>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Interrupt this run?"
        description="The agent stops now. Continue afterwards starts a new run in this session; it may not pick up where this one stopped."
        confirmLabel="Interrupt"
        destructive
        onConfirm={interrupt}
      />
    </div>
  );
}
