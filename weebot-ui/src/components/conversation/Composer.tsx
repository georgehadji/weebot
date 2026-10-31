"use client";

/**
 * Composer — always-enabled input for the conversation pane.
 *
 * Replaces the old session page's composer, which only unlocked once the
 * agent emitted a wait_for_user event (RC-6 in the implementation plan) —
 * you could not interject mid-run, ask a follow-up after completion, or
 * even start talking without a separate "new session" page first.
 *
 * One text box, four possible backend actions (start / resume / steer /
 * chat) resolved server-side from session status (see
 * dispatch_session_input.py) — the mode chip here is purely informational,
 * mirroring what the backend will do, not a client-side branch.
 *
 * The behaviour (states, drafts, sending) lives in `useComposer`; this is its view. The box is
 * never disabled while a message is in flight, and Enter does not send mid-IME-composition.
 */

import { KeyboardEvent, useEffect, useRef } from "react";
import { Loader2, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { canSubmit } from "@/lib/composer";
import { useComposer } from "@/hooks/useComposer";
import { DeliveryState, MessageEvent } from "@/types/events";

export type SessionLifecycleStatus =
  | "none" // no session yet — first message of a new conversation
  | "pending"
  | "running"
  | "waiting"
  | "completed"
  | "failed";

interface ComposerProps {
  sessionId: string | null;
  status: SessionLifecycleStatus;
  model?: string;
  onSessionCreated: (sessionId: string) => void;
  onOptimisticMessage: (event: MessageEvent) => void;
  onDelivery: (id: string, delivery: DeliveryState) => void;
  /** Receives the function that re-sends a failed message (wired to the timeline's Retry). */
  registerRetry?: (retry: (event: MessageEvent) => void) => void;
  /** Receives the function that replaces the draft (used by the example prompts). */
  registerSetDraft?: (setDraft: (text: string) => void) => void;
  className?: string;
}

const MODE_LABEL: Record<SessionLifecycleStatus, string> = {
  none: "Start task",
  pending: "Start task",
  failed: "Retry task",
  waiting: "Reply",
  running: "Steer",
  completed: "Chat",
};

const MODE_PLACEHOLDER: Record<SessionLifecycleStatus, string> = {
  none: "Message weebot… (e.g. \"refactor the cascade module\")",
  pending: "Message weebot…",
  failed: "Message weebot…",
  waiting: "Type your response…",
  running: "Steer the agent while it works…",
  completed: "Ask a follow-up…",
};

export function Composer({
  sessionId,
  status,
  model,
  onSessionCreated,
  onOptimisticMessage,
  onDelivery,
  registerRetry,
  registerSetDraft,
  className,
}: ComposerProps) {
  const { state, edit, submit, retry } = useComposer({
    sessionId,
    model,
    onSessionCreated,
    onOptimisticMessage,
    onDelivery,
  });
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sending = state.phase === "sending";

  useEffect(() => {
    registerRetry?.(retry);
  }, [registerRetry, retry]);
  useEffect(() => {
    registerSetDraft?.((text) => {
      edit(text);
      textareaRef.current?.focus();
    });
  }, [registerSetDraft, edit]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // isComposing: Enter confirms an IME candidate (Greek tonos, CJK, ...), it must not send.
    // Safari reports that Enter after compositionend with isComposing false but keyCode 229.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className={cn("border-t bg-surface-2 p-3", className)}>
      <div className="mb-1.5 flex items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
            status === "running"
              ? "border-status-live/40 text-status-live-fg"
              : status === "waiting"
              ? "border-status-waiting/40 text-status-waiting-fg"
              : "border-border text-muted-foreground"
          )}
        >
          {MODE_LABEL[status]}
        </span>
        {sending && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            Sending…
          </span>
        )}
      </div>
      <div className="flex items-end gap-2">
        <Textarea
          ref={textareaRef}
          value={state.draft}
          onChange={(e) => edit(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={MODE_PLACEHOLDER[status]}
          rows={1}
          aria-label="Message weebot"
          aria-invalid={state.phase === "failed" || undefined}
          aria-describedby="composer-hint"
          className="max-h-40 min-h-11 flex-1 resize-none overflow-y-auto bg-surface-1"
        />
        <Button onClick={submit} disabled={!canSubmit(state)} size="icon" aria-label="Send message">
          <Send className="h-4 w-4" />
        </Button>
      </div>
      {state.phase === "failed" && state.error && (
        <p role="alert" className="mt-1 text-xs text-status-error-fg">
          Not sent: {state.error}. Your message is back in the box.
        </p>
      )}
      <p id="composer-hint" className="mt-1 text-xs text-muted-foreground">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  );
}
