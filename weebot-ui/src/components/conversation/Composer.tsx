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
 * The behaviour (states, drafts, sending) lives in `useComposer`; this is its view. It is a
 * <form>, so the Send button and Enter share one submit path. The box is never disabled while a
 * message is in flight, and Enter does not send mid-IME-composition.
 */

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { Loader2, Send } from "lucide-react";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { canSubmit } from "@/lib/composer";
import { STORAGE_KEYS } from "@/lib/storage";
import { useComposer } from "@/hooks/useComposer";
import { useStoredValue } from "@/hooks/useStoredValue";
import { useAnnounce } from "@/providers/AnnouncerProvider";
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
  onDelivery: (id: string, delivery: DeliveryState) => DeliveryState | undefined;
  /** Receives the function that re-sends a failed message (wired to the timeline's Retry). */
  registerRetry?: (retry: (event: MessageEvent) => void) => void;
  /** Receives the function that replaces the draft (used by the example prompts). */
  registerSetDraft?: (setDraft: (text: string) => void) => void;
  /** Receives the function used by approval and plan-review buttons. */
  registerQuickReply?: (reply: (text: string) => Promise<boolean>) => void;
  /** Receives the function that moves focus into the box (plan review's "Request changes"). */
  registerFocus?: (focus: () => void) => void;
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
  none: "Message weebot… (e.g. “refactor the cascade module”)",
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
  registerQuickReply,
  registerFocus,
  className,
}: ComposerProps) {
  // Remembers the Auto switch across sessions; the server render cannot see it, so it starts off.
  const [storedMode, setStoredMode] = useStoredValue("local", STORAGE_KEYS.executionMode);
  const autoMode = storedMode === "auto";
  const [confirmingAuto, setConfirmingAuto] = useState(false);
  const announce = useAnnounce();
  const { state, edit, submit, submitText, retry } = useComposer({
    sessionId,
    model,
    executionMode: autoMode ? "auto" : "interactive",
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
  useEffect(() => {
    registerQuickReply?.(submitText);
  }, [registerQuickReply, submitText]);
  useEffect(() => {
    registerFocus?.(() => textareaRef.current?.focus());
  }, [registerFocus]);

  const setAuto = (on: boolean) => {
    setStoredMode(on ? "auto" : "interactive");
    announce(on ? "Auto mode on. Tool calls run without asking." : "Auto mode off. Approvals are back.");
  };

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    submit();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // isComposing: Enter confirms an IME candidate (Greek tonos, CJK, ...), it must not send.
    // Safari reports that Enter after compositionend with isComposing false but keyCode 229.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <form onSubmit={handleSubmit} className={cn("border-t bg-surface-2 px-3 pt-3 pb-safe", className)}>
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
            <Loader2 className="h-3 w-3 motion-safe:animate-spin" aria-hidden="true" />
            Sending…
          </span>
        )}
        {/* Visible while on: Auto skips approvals, which a hover-only title hid from touch users. */}
        <span
          id="composer-auto-hint"
          className={cn("ml-auto text-xs text-status-waiting-fg", !autoMode && "sr-only")}
        >
          Runs without approvals, gates or questions
        </span>
        {/* The wrapping label is the switch's name, so it is exactly the visible "Auto". */}
        <label
          className={cn(
            "flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground pointer-coarse:min-h-11",
            !autoMode && "ml-auto"
          )}
        >
          <Switch
            checked={autoMode}
            // Turning Auto on skips every approval prompt, so it asks first; turning it off is safe.
            onCheckedChange={(on) => (on ? setConfirmingAuto(true) : setAuto(false))}
            aria-describedby="composer-auto-hint"
          />
          Auto
        </label>
      </div>
      <div className="flex items-end gap-2">
        <Textarea
          ref={textareaRef}
          value={state.draft}
          onChange={(e) => edit(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={MODE_PLACEHOLDER[status]}
          rows={1}
          name="message"
          autoComplete="off"
          enterKeyHint="send"
          aria-label="Message weebot"
          aria-invalid={state.phase === "failed" || undefined}
          aria-describedby={state.phase === "failed" && state.error ? "composer-error composer-hint" : "composer-hint"}
          className="max-h-40 min-h-11 flex-1 resize-none overflow-y-auto bg-surface-1"
        />
        {/* `loading` (not `disabled`) while sending, so focus stays on the button. */}
        <Button
          type="submit"
          loading={sending}
          disabled={!sending && !canSubmit(state)}
          size="icon"
          aria-label="Send message"
        >
          <Send className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
      {state.phase === "failed" && state.error && (
        <p id="composer-error" role="alert" className="mt-1 text-xs text-status-error-fg">
          Not sent: {state.error}. Your message is back in the box.
        </p>
      )}
      <p id="composer-hint" className="mt-1 text-xs text-muted-foreground">
        Enter to send · Shift+Enter for a new line
      </p>
      <ConfirmDialog
        open={confirmingAuto}
        onOpenChange={setConfirmingAuto}
        title="Turn on Auto mode?"
        description="Auto skips approval prompts for tool calls. The agent runs them without asking you first."
        confirmLabel="Turn on Auto"
        onConfirm={() => setAuto(true)}
      />
    </form>
  );
}
