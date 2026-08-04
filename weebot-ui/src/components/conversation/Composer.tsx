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
 */

import { useState, useRef, KeyboardEvent } from "react";
import { Loader2, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useToast } from "@/providers/ToastProvider";
import { MessageEvent } from "@/types/events";

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

function makeClientMsgId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `client-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function Composer({
  sessionId,
  status,
  model,
  onSessionCreated,
  onOptimisticMessage,
  className,
}: ComposerProps) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { toast } = useToast();

  const handleSend = async () => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    setSending(true);
    const clientMsgId = makeClientMsgId();
    onOptimisticMessage({
      type: "message",
      id: clientMsgId,
      timestamp: new Date().toISOString(),
      session_id: sessionId ?? "",
      role: "user",
      message: trimmed,
    });
    setText("");

    try {
      if (!sessionId) {
        const session = await api.sessions.create({ prompt: trimmed, model });
        await api.sessions.run(session.id);
        onSessionCreated(session.id);
      } else {
        await api.sessions.input(sessionId, trimmed, { clientMsgId, model });
      }
    } catch (e) {
      const description = e instanceof Error ? e.message : "Unknown error";
      toast({ title: "Failed to send message", description, variant: "error" });
      setText(trimmed); // restore so the user doesn't lose their draft
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className={cn("border-t bg-surface-2 p-3", className)}>
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
            status === "running"
              ? "border-status-live/40 text-status-live"
              : status === "waiting"
              ? "border-status-waiting/40 text-status-waiting"
              : "border-border text-muted-foreground"
          )}
        >
          {MODE_LABEL[status]}
        </span>
      </div>
      <div className="flex gap-2 items-end">
        <Textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={MODE_PLACEHOLDER[status]}
          rows={2}
          disabled={sending}
          className="flex-1 resize-none bg-surface-1"
          aria-label="Message weebot"
        />
        <Button
          onClick={handleSend}
          disabled={!text.trim() || sending}
          size="icon"
          aria-label="Send message"
        >
          {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </Button>
      </div>
      <p className="text-[11px] text-muted-foreground mt-1">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  );
}
