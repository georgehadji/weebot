/**
 * session-reducer — pure event-sourcing projection from a raw AgentEvent
 * stream to what the conversation timeline should render.
 *
 * No DOM, no fetch, no React — a plain (state, event) => state function so
 * it's trivially unit-testable and reusable by both the live WebSocket/SSE
 * path and "replay this session's stored events" on page load.
 *
 * Responsibilities:
 *   - Dedupe by event.id (BaseEvent.id is already a stable uuid) — fixes
 *     duplicate rows on reconnect and the `key={i}` index-key bug the old
 *     session page had.
 *   - Collapse a tool call's `calling` → `called` pair into one display
 *     row instead of two, keyed by tool_call_id, shown at the position
 *     the call first appeared (not wherever the `called` update arrives).
 *   - Surface gap markers from the "N event(s) dropped" notification
 *     events T0.5's bounded queue emits, so a lost event reads as a
 *     visible seam instead of silently vanishing.
 */

import { AgentEvent, ToolEvent } from "@/types/events";

/** A display-order key: either an event's own id, or `tool:{tool_call_id}` for ToolEvents. */
type DisplayKey = string;

export interface GapMarker {
  kind: "gap";
  key: string;
  droppedCount: number;
}

export interface SessionViewState {
  eventsById: ReadonlyMap<string, AgentEvent>;
  toolCallsByCallId: ReadonlyMap<string, ToolEvent>;
  gapMarkersByKey: ReadonlyMap<string, GapMarker>;
  displayOrder: readonly DisplayKey[];
}

export const initialSessionViewState: SessionViewState = {
  eventsById: new Map(),
  toolCallsByCallId: new Map(),
  gapMarkersByKey: new Map(),
  displayOrder: [],
};

function toolDisplayKey(toolCallId: string): DisplayKey {
  return `tool:${toolCallId}`;
}

const DROPPED_PATTERN = /^(\d+) event\(s\) dropped/;

export function sessionReducer(state: SessionViewState, event: AgentEvent): SessionViewState {
  // Idempotent — replaying an already-seen event (e.g. after a reconnect
  // re-syncs history) must not duplicate a row.
  if (state.eventsById.has(event.id)) {
    return state;
  }

  const eventsById = new Map(state.eventsById).set(event.id, event);

  if (event.type === "tool") {
    const toolEvent = event as ToolEvent;
    const key = toolDisplayKey(toolEvent.tool_call_id);
    const toolCallsByCallId = new Map(state.toolCallsByCallId).set(toolEvent.tool_call_id, toolEvent);
    const alreadyDisplayed = state.toolCallsByCallId.has(toolEvent.tool_call_id);
    const displayOrder = alreadyDisplayed ? state.displayOrder : [...state.displayOrder, key];
    return { ...state, eventsById, toolCallsByCallId, displayOrder };
  }

  if (event.type === "notification") {
    const match = DROPPED_PATTERN.exec((event as { text: string }).text ?? "");
    if (match) {
      const gapMarkersByKey = new Map(state.gapMarkersByKey).set(event.id, {
        kind: "gap",
        key: event.id,
        droppedCount: parseInt(match[1], 10),
      });
      return {
        ...state,
        eventsById,
        gapMarkersByKey,
        displayOrder: [...state.displayOrder, event.id],
      };
    }
  }

  return { ...state, eventsById, displayOrder: [...state.displayOrder, event.id] };
}

export function reduceSessionEvents(events: readonly AgentEvent[]): SessionViewState {
  return events.reduce(sessionReducer, initialSessionViewState);
}

export type DisplayItem = { kind: "event"; event: AgentEvent } | GapMarker;

/** Resolve displayOrder into the actual rows to render, in order. */
export function getDisplayItems(state: SessionViewState): DisplayItem[] {
  return state.displayOrder.map((key) => {
    const gap = state.gapMarkersByKey.get(key);
    if (gap) return gap;

    if (key.startsWith("tool:")) {
      const toolCallId = key.slice("tool:".length);
      const toolEvent = state.toolCallsByCallId.get(toolCallId);
      if (toolEvent) return { kind: "event", event: toolEvent };
    }

    const event = state.eventsById.get(key);
    return { kind: "event", event: event! };
  });
}
