"use client";

import { useCallback, useEffect, useReducer } from "react";
import { api } from "@/lib/api";
import { composerReducer, initialComposerState } from "@/lib/composer";
import { draftKey, readStored, writeStored } from "@/lib/storage";
import { useAnnounce } from "@/providers/AnnouncerProvider";
import { useToast } from "@/providers/ToastProvider";
import { DeliveryState, MessageEvent } from "@/types/events";

function makeClientMsgId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `client-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface UseComposerOptions {
  sessionId: string | null;
  model?: string;
  /** "auto" runs the flow without human pauses; "interactive" is the default. */
  executionMode?: "auto" | "interactive";
  onSessionCreated: (sessionId: string) => void;
  /** Show the user's message in the timeline immediately (with delivery "sending"). */
  onOptimisticMessage: (event: MessageEvent) => void;
  /**
   * Report how a send ended so the timeline row can settle or offer a retry. Returns the row's
   * resulting state: "sent" if the server's echo had already settled it, whatever was reported.
   */
  onDelivery: (id: string, delivery: DeliveryState) => DeliveryState | undefined;
}

/**
 * The composer's behaviour: a reducer (lib/composer.ts) for its states, a per-session draft
 * kept in sessionStorage (through lib/storage, which never throws), and the send itself.
 */
export function useComposer({
  sessionId,
  model,
  executionMode,
  onSessionCreated,
  onOptimisticMessage,
  onDelivery,
}: UseComposerOptions) {
  const key = draftKey(sessionId);
  const { toast } = useToast();
  const announce = useAnnounce();
  const [state, dispatch] = useReducer(composerReducer, "", initialComposerState);

  // Read after hydration: the server render cannot see sessionStorage, and reading it in the
  // initializer made the first client render differ from the HTML (a hydration mismatch on the
  // Send button whenever a draft was saved). Declared before the write below so it reads first.
  useEffect(() => {
    const saved = readStored("session", key);
    if (saved) dispatch({ type: "edit", draft: saved });
  }, [key]);

  useEffect(() => {
    writeStored("session", key, state.draft || null);
  }, [key, state.draft]);

  const deliver = useCallback(
    async (text: string, clientMsgId: string) => {
      try {
        if (!sessionId) {
          const session = await api.sessions.create({
            prompt: text,
            model,
            execution_mode: executionMode,
          });
          try {
            await api.sessions.run(session.id);
          } catch (e) {
            // The session exists, so a retry would create a second one. Open it instead: the
            // page shows its real status and the run controls.
            console.warn("[Composer] starting the run failed; opening the session anyway", e);
            toast({
              title: "Task created but not started",
              description: e instanceof Error ? e.message : "Unknown error",
              variant: "error",
            });
          }
          onDelivery(clientMsgId, "sent");
          dispatch({ type: "sent" });
          onSessionCreated(session.id);
          return true;
        } else {
          await api.sessions.input(sessionId, text, { clientMsgId, model, executionMode });
          onDelivery(clientMsgId, "sent");
          dispatch({ type: "sent" });
          return true;
        }
      } catch (e) {
        // An echoed row is delivered (the timeline shows it so): do not claim "Not sent".
        if (onDelivery(clientMsgId, "failed") === "sent") {
          dispatch({ type: "sent" });
          return true;
        }
        dispatch({ type: "failed", error: e instanceof Error ? e.message : "Unknown error", text });
        // The failed row is not a live region (see lib/announce.ts), so say it here.
        announce("Message not sent. Retry Sending is available.");
        return false;
      }
    },
    [sessionId, model, executionMode, onDelivery, onSessionCreated, toast, announce]
  );

  /** Resolves true once the message is delivered; false if it was refused or failed. */
  const submitText = useCallback(
    async (rawText: string): Promise<boolean> => {
      const text = rawText.trim();
      if (!text || state.phase === "sending") return false;
      const clientMsgId = makeClientMsgId();
      dispatch({ type: "submit" });
      onOptimisticMessage({
        type: "message",
        id: clientMsgId,
        timestamp: new Date().toISOString(),
        session_id: sessionId ?? "",
        role: "user",
        message: text,
        delivery: "sending",
      });
      return deliver(text, clientMsgId);
    },
    [state.phase, sessionId, onOptimisticMessage, deliver]
  );

  const submit = useCallback(() => {
    void submitText(state.draft);
  }, [state.draft, submitText]);

  /** Re-send a message whose delivery failed; it keeps its row (same id) in the timeline. */
  const retry = useCallback(
    (event: MessageEvent) => {
      if (state.phase === "sending") return; // one send in flight at a time, as submit
      dispatch({ type: "retry" });
      if (state.draft === event.message) dispatch({ type: "edit", draft: "" });
      onDelivery(event.id, "sending");
      void deliver(event.message, event.id);
    },
    [state.draft, state.phase, onDelivery, deliver]
  );

  const edit = useCallback((draft: string) => dispatch({ type: "edit", draft }), []);

  return { state, edit, submit, submitText, retry };
}
