"use client";

/**
 * RunControls — surfaces the already-existing (but previously unexposed)
 * cancel endpoint while a session is running. Steering text itself goes
 * through the Composer (POST /sessions/{id}/input resolves to the steer
 * strategy automatically when status === "running") — this button is for
 * "stop entirely," not "say something."
 */

import { useState } from "react";
import { Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useToast } from "@/providers/ToastProvider";

export function RunControls({ sessionId }: { sessionId: string }) {
  const [cancelling, setCancelling] = useState(false);
  const { toast } = useToast();

  const handleInterrupt = async () => {
    setCancelling(true);
    try {
      await api.sessions.cancel(sessionId);
      toast({ title: "Session interrupted", variant: "success" });
    } catch (e) {
      const description = e instanceof Error ? e.message : "Unknown error";
      toast({ title: "Failed to interrupt session", description, variant: "error" });
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div className="flex items-center justify-end border-t bg-surface-2 px-3 py-1.5">
      <Button
        variant="ghost"
        size="sm"
        onClick={handleInterrupt}
        disabled={cancelling}
        className="text-status-error hover:text-status-error hover:bg-status-error/10"
      >
        <Square className="h-3.5 w-3.5 mr-1.5" />
        {cancelling ? "Interrupting…" : "Interrupt"}
      </Button>
    </div>
  );
}
