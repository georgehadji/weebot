"use client";

import { useCallback, useEffect, useReducer } from "react";
import { api } from "@/lib/api";
import { composerReducer, initialComposerState } from "@/lib/composer";
import { DeliveryState, MessageEvent } from "@/types/events";

function draftKey(sessionId: string | null): string {
  return `weebot_draft:${sessionId ?? "new"}`;
}

// sessionStorage can throw (privacy mode, quota); a lost draft is never worth an error.
function readDraft(key: string): string {
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeDraft(key: string, draft: string): void {
  try {
    if (draft) window.sessionStorage.setItem(key, draft);
    else window.sessionStorage.removeItem(key);
  } catch {
    // ignore
  }
}

function makeClientMsgId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `client-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface UseComposerOptions {
  sessionId: string | null;
  model?: string;
  onSessionCreated: (sessionId: string) => void;
  /** Show the user's message in the timeline immediately (with delivery "sending"). */
  onOptimisticMessage: (event: MessageEvent) => void;
  /** Report how a send ended so the timeline row can settle or offer a retry. */
  onDelivery: (id: string, delivery: DeliveryState) => void;
}

/**
 * The composer's behaviour: a reducer (lib/composer.ts) for its states, a per-session draft
 * kept in sessionStorage, and the send itself.
 */
export function useComposer({
  sessionId,
  model,
  onSessionCreated,
  onOptimisticMessage,
  onDelivery,
}: UseComposerOptions) {
  const key = draftKey(sessionId);
  const [state, dispatch] = useReducer(composerReducer, key, (k) => initialComposerState(readDraft(k)));

  useEffect(() => {
    writeDraft(key, state.draft);
  }, [key, state.draft]);

  const deliver = useCallback(
    async (text: string, clientMsgId: string) => {
      try {
        if (!sessionId) {
          const session = await api.sessions.create({ prompt: text, model });
          await api.sessions.run(session.id);
          onDelivery(clientMsgId, "sent");
          dispatch({ type: "sent" });
          onSessionCreated(session.id);
        } else {
          await api.sessions.input(sessionId, text, { clientMsgId, model });
          onDelivery(clientMsgId, "sent");
          dispatch({ type: "sent" });
        }
      } catch (e) {
        onDelivery(clientMsgId, "failed");
        dispatch({ type: "failed", error: e instanceof Error ? e.message : "Unknown error", text });
      }
    },
    [sessionId, model, onDelivery, onSessionCreated]
  );

  const submit = useCallback(() => {
    const text = state.draft.trim();
    if (!text || state.phase === "sending") return;
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
    void deliver(text, clientMsgId);
  }, [state.draft, state.phase, sessionId, onOptimisticMessage, deliver]);

  /** Re-send a message whose delivery failed; it keeps its row (same id) in the timeline. */
  const retry = useCallback(
    (event: MessageEvent) => {
      if (state.draft === event.message) dispatch({ type: "edit", draft: "" });
      onDelivery(event.id, "sending");
      void deliver(event.message, event.id);
    },
    [state.draft, onDelivery, deliver]
  );

  const edit = useCallback((draft: string) => dispatch({ type: "edit", draft }), []);

  return { state, edit, submit, retry };
}
