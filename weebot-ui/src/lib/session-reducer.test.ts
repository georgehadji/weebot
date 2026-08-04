import { describe, it, expect } from "vitest";
import {
  sessionReducer,
  reduceSessionEvents,
  getDisplayItems,
  initialSessionViewState,
} from "./session-reducer";
import { AgentEvent, MessageEvent, ToolEvent, NotificationEvent } from "@/types/events";

function message(id: string, text: string): MessageEvent {
  return {
    type: "message",
    id,
    timestamp: "2026-01-01T00:00:00Z",
    session_id: "s1",
    role: "assistant",
    message: text,
  };
}

function toolEvent(id: string, toolCallId: string, status: "calling" | "called", result?: string): ToolEvent {
  return {
    type: "tool",
    id,
    timestamp: "2026-01-01T00:00:00Z",
    session_id: "s1",
    tool_call_id: toolCallId,
    tool_name: "bash",
    function_name: "run",
    function_args: {},
    status,
    result,
  };
}

function droppedNotification(id: string, count: number): NotificationEvent {
  return {
    type: "notification",
    id,
    timestamp: "2026-01-01T00:00:00Z",
    session_id: "",
    text: `${count} event(s) dropped — client fell behind`,
  };
}

describe("sessionReducer", () => {
  it("appends events to display order in arrival order", () => {
    const state = reduceSessionEvents([message("1", "hi"), message("2", "there")]);
    const items = getDisplayItems(state);
    expect(items).toHaveLength(2);
    expect(items[0]).toEqual({ kind: "event", event: message("1", "hi") });
    expect(items[1]).toEqual({ kind: "event", event: message("2", "there") });
  });

  it("is idempotent — replaying the same event id is a no-op", () => {
    const first = sessionReducer(initialSessionViewState, message("1", "hi"));
    const second = sessionReducer(first, message("1", "hi"));
    expect(second).toBe(first); // same reference — nothing changed
    expect(getDisplayItems(second)).toHaveLength(1);
  });

  it("collapses a calling→called tool pair into a single display row", () => {
    const state = reduceSessionEvents([
      message("m1", "starting"),
      toolEvent("t1", "call-abc", "calling"),
      toolEvent("t2", "call-abc", "called", "output here"),
    ]);
    const items = getDisplayItems(state);

    expect(items).toHaveLength(2); // message + one collapsed tool row, not two
    const toolItem = items[1];
    expect(toolItem.kind).toBe("event");
    if (toolItem.kind === "event" && toolItem.event.type === "tool") {
      expect(toolItem.event.status).toBe("called");
      expect(toolItem.event.result).toBe("output here");
    }
  });

  it("keeps the tool row at its first-occurrence position, not where 'called' arrives", () => {
    const state = reduceSessionEvents([
      toolEvent("t1", "call-abc", "calling"),
      message("m1", "meanwhile"),
      toolEvent("t2", "call-abc", "called", "done"),
    ]);
    const items = getDisplayItems(state);

    expect(items).toHaveLength(2);
    expect(items[0].kind).toBe("event");
    if (items[0].kind === "event") expect(items[0].event.type).toBe("tool");
    expect(items[1].kind).toBe("event");
    if (items[1].kind === "event") expect(items[1].event.id).toBe("m1");
  });

  it("distinct tool_call_ids never collapse into each other", () => {
    const state = reduceSessionEvents([
      toolEvent("t1", "call-a", "calling"),
      toolEvent("t2", "call-b", "calling"),
    ]);
    expect(getDisplayItems(state)).toHaveLength(2);
  });

  it("surfaces a dropped-event gap marker", () => {
    const state = reduceSessionEvents([message("m1", "hi"), droppedNotification("n1", 7)]);
    const items = getDisplayItems(state);

    expect(items).toHaveLength(2);
    expect(items[1]).toEqual({ kind: "gap", key: "n1", droppedCount: 7 });
  });

  it("a notification without the drop pattern renders as a normal event, not a gap", () => {
    const plain: NotificationEvent = {
      type: "notification",
      id: "n2",
      timestamp: "2026-01-01T00:00:00Z",
      session_id: "s1",
      text: "session completed",
    };
    const state = reduceSessionEvents([plain]);
    const items = getDisplayItems(state);
    expect(items[0]).toEqual({ kind: "event", event: plain });
  });

  it("reduceSessionEvents over an empty list returns the initial state", () => {
    expect(reduceSessionEvents([])).toEqual(initialSessionViewState);
  });
});
