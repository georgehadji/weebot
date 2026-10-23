"use client";

/**
 * ConversationPane — the timeline + composer for one session.
 *
 * Uses a native, explicitly overflowed timeline so every message remains
 * reachable by mouse wheel, trackpad, keyboard, and touch. It only
 * auto-scrolls when the operator was already at the bottom.
 */

import { useEffect, useRef, useState } from "react";
import { ArrowDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
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
  useSessionEvents(sessionId ?? undefined, (event) => {
    setState((prev) => sessionReducer(prev, event));
  });
  const viewportRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);

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
    setShowJumpToLatest(!atBottomRef.current);
  };

  const jumpToLatest = () => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;
    atBottomRef.current = true;
    setShowJumpToLatest(false);
  };

  useEffect(() => {
    if (atBottomRef.current && viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [items.length]);

  const isRunning = status === "running";

  return (
    <div className="flex h-full flex-col">
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={viewportRef}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
          onScroll={handleScroll}
          aria-label="Conversation messages"
          tabIndex={0}
        >
          <div className="space-y-3 p-4">
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
        </div>
        {showJumpToLatest && (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-md"
            onClick={jumpToLatest}
          >
            <ArrowDown className="h-3.5 w-3.5" />
            Jump to latest
          </Button>
        )}
      </div>

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
