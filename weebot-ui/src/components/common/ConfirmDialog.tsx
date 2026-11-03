"use client";

import { useRef } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAsyncAction } from "@/hooks/useAsyncAction";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive. */
  destructive?: boolean;
  /**
   * May return a promise. The dialog then stays open with a busy confirm button, closes when it
   * resolves, and shows the failure inline (still open, so the user can retry or cancel).
   */
  onConfirm: () => unknown;
}

/**
 * ConfirmDialog — replaces `window.confirm`: names what is affected, focuses the safe action
 * (Cancel) first, and is a real dialog (Escape cancels, focus returns to the trigger).
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  destructive,
  onConfirm,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const { state, run, reset, pending } = useAsyncAction(onConfirm);

  const change = (next: boolean) => {
    if (!next && pending) return; // do not walk away from a request that is still in flight
    if (!next) reset();
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => change(next)}>
      <DialogContent showCloseButton={false} initialFocus={cancelRef}>
        <DialogTitle>{title}</DialogTitle>
        {description && <DialogDescription>{description}</DialogDescription>}
        {state.status === "error" && (
          <p role="alert" className="text-sm text-status-error-fg">
            Couldn’t finish that: {state.error}. Try again, or cancel.
          </p>
        )}
        <DialogFooter>
          <Button ref={cancelRef} variant="outline" onClick={() => change(false)}>
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? "destructive" : "default"}
            loading={pending}
            onClick={async () => {
              if (await run()) change(false);
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
