"use client";

/**
 * ConversationPane — the timeline + composer for one session.
 *
 * Fixes RC-7 (auto-scroll wrote to ScrollArea's non-scrolling Root
 * instead of its Viewport) via ScrollArea's new `viewportRef` prop, and
 * only auto-scrolls when the user was already at the bottom — so reading
 * scrollback while new events stream in doesn't get yanked away.
 */

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Composer, SessionLifecycleStatus } from "./Composer";
import { EventRenderer } from "./EventRenderer";
import { GapMarkerRow } from "./GapMarkerRow";
import { RunControls } from "./RunControls";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { sessionReducer, getDisplayItems, initialSessionViewState, SessionViewState } from "@/lib/session-reducer";
import { AgentEvent, MessageEvent } from "@/types/events";

const STICK_TO_BOTTOM_THRESHOLD_PX = 80;

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
  const { lastMessage } = useSessionEvents(sessionId ?? undefined);
  const viewportRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);

  useEffect(() => {
    if (lastMessage) {
      setState((prev) => sessionReducer(prev, lastMessage));
    }
  }, [lastMessage]);

  const addOptimisticMessage = (event: MessageEvent) => {
    setState((prev) => sessionReducer(prev, event));
  };

  const items = getDisplayItems(state);

  // Track whether the user is scrolled to the bottom so new events don't
  // yank the view away from scrollback they're actively reading.
  const handleScroll = () => {
    const el = viewportRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    atBottomRef.current = distanceFromBottom < STICK_TO_BOTTOM_THRESHOLD_PX;
  };

  useEffect(() => {
    if (atBottomRef.current && viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [items.length]);

  const isRunning = status === "running";

  return (
    <div className="flex h-full flex-col">
      <ScrollArea className="flex-1" viewportRef={viewportRef}>
        <div className="space-y-3 p-4" onScroll={handleScroll}>
          {items.length === 0 ? (
            <div className="flex h-full items-center justify-center py-16 text-sm text-muted-foreground">
              {sessionId ? "Waiting for events…" : "Start a conversation below."}
            </div>
          ) : (
            items.map((item) =>
              item.kind === "gap" ? (
                <GapMarkerRow key={item.key} droppedCount={item.droppedCount} />
              ) : (
                <EventRenderer key={item.event.id} event={item.event} />
              )
            )
          )}
          {isRunning && (
            <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>Agent is working…</span>
            </div>
          )}
        </div>
      </ScrollArea>

      {isRunning && sessionId && <RunControls sessionId={sessionId} />}

      <Composer
        sessionId={sessionId}
        status={status}
        model={model}
        onSessionCreated={onSessionCreated}
        onOptimisticMessage={addOptimisticMessage}
      />
    </div>
  );
}
