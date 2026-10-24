"use client";

/**
 * ConversationPane — the timeline + composer for one session.
 *
 * The timeline sticks to the newest row only while the reader is at the bottom
 * (`useStickToBottom`); scrolled up, a "Jump to latest" pill counts what arrived. It is a
 * `role="log"` that is not itself announced — only coarse moments (a step done, a question,
 * an error) reach screen readers, through the AnnouncerProvider.
 *
 * User messages appear immediately with a delivery state; the server's echo settles them and a
 * failed send keeps its row with a Retry.
 */

import { useCallback, useRef, useState } from "react";
import { ArrowDown, Loader2 } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Composer, SessionLifecycleStatus } from "./Composer";
import { EventRenderer } from "./EventRenderer";
import { GapMarkerRow } from "./GapMarkerRow";
import { RunControls } from "./RunControls";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { useStickToBottom } from "@/hooks/useStickToBottom";
import { announcementFor } from "@/lib/announce";
import {
  getDisplayItems,
  initialSessionViewState,
  markDelivery,
  sessionReducer,
  SessionViewState,
} from "@/lib/session-reducer";
import { useAnnounce } from "@/providers/AnnouncerProvider";
import { AgentEvent, DeliveryState, MessageEvent } from "@/types/events";

const EXAMPLE_PROMPTS = [
  "Summarise the files in my Downloads folder",
  "Find and fix the failing test in this project",
  "Research the latest news on a topic and write me a brief",
];

interface ConversationPaneProps {
  sessionId: string | null;
  status: SessionLifecycleStatus;
  initialEvents?: AgentEvent[];
  model?: string;
  onSessionCreated: (sessionId: string) => void;
}

export function ConversationPane({
  sessionId,
  status,
  initialEvents,
  model,
  onSessionCreated,
}: ConversationPaneProps) {
  const [state, setState] = useState<SessionViewState>(() =>
    (initialEvents ?? []).reduce(sessionReducer, initialSessionViewState)
  );
  // Ids already shown, so a reconnect replaying history is not announced a second time.
  const [seen] = useState(() => new Set((initialEvents ?? []).map((e) => e.id)));
  const announce = useAnnounce();

  useSessionEvents(sessionId ?? undefined, (event) => {
    setState((prev) => sessionReducer(prev, event));
    if (seen.has(event.id)) return;
    seen.add(event.id);
    const text = announcementFor(event);
    if (text) announce(text);
  });

  const addOptimisticMessage = useCallback(
    (event: MessageEvent) => setState((prev) => sessionReducer(prev, event)),
    []
  );
  const settleDelivery = useCallback(
    (id: string, delivery: DeliveryState) => setState((prev) => markDelivery(prev, id, delivery)),
    []
  );
  const retryRef = useRef<(event: MessageEvent) => void>(undefined);
  const registerRetry = useCallback((fn: (event: MessageEvent) => void) => {
    retryRef.current = fn;
  }, []);
  const setDraftRef = useRef<(text: string) => void>(undefined);
  const registerSetDraft = useCallback((fn: (text: string) => void) => {
    setDraftRef.current = fn;
  }, []);
  const onRetry = useCallback((event: MessageEvent) => retryRef.current?.(event), []);

  const items = getDisplayItems(state);
  const { viewportRef, sentinelRef, atBottom, unseen, scrollToBottom } = useStickToBottom(items.length);
  const isRunning = status === "running";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative flex min-h-0 flex-1 flex-col">
        <ScrollArea className="min-h-0 flex-1" viewportRef={viewportRef}>
          <div role="log" aria-label="Conversation" aria-live="off" className="space-y-3 p-4">
            {items.length === 0 ? (
              sessionId ? (
                <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
                  Waiting for events…
                </div>
              ) : (
                <div className="mx-auto flex max-w-xl flex-col items-center gap-3 py-12 text-center">
                  <p className="text-sm text-muted-foreground">Start a conversation below, or try one of these:</p>
                  <ul className="flex flex-wrap justify-center gap-2">
                    {EXAMPLE_PROMPTS.map((prompt) => (
                      <li key={prompt}>
                        <button
                          type="button"
                          onClick={() => setDraftRef.current?.(prompt)}
                          className="rounded-full border bg-surface-2 px-3 py-1.5 text-xs transition-colors hover:bg-surface-3 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {prompt}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )
            ) : (
              items.map((item) =>
                item.kind === "gap" ? (
                  <GapMarkerRow key={item.key} droppedCount={item.droppedCount} />
                ) : (
                  <EventRenderer key={item.event.id} event={item.event} onRetry={onRetry} />
                )
              )
            )}
            {isRunning && (
              <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                <span>Agent is working…</span>
              </div>
            )}
            <div ref={sentinelRef} aria-hidden="true" className="h-px" />
          </div>
        </ScrollArea>

        {!atBottom && (
          <button
            type="button"
            onClick={scrollToBottom}
            className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border bg-surface-2 px-3 py-1.5 text-xs font-medium shadow-lg transition-colors hover:bg-surface-3 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
            Jump to latest
            {unseen > 0 && <span className="text-muted-foreground">· {unseen} new</span>}
          </button>
        )}
      </div>

      {isRunning && sessionId && <RunControls sessionId={sessionId} />}

      <Composer
        sessionId={sessionId}
        status={status}
        model={model}
        onSessionCreated={onSessionCreated}
        onOptimisticMessage={addOptimisticMessage}
        onDelivery={settleDelivery}
        registerRetry={registerRetry}
        registerSetDraft={registerSetDraft}
      />
    </div>
  );
}
