/**
 * W2 — what the session reducer guarantees, one test per guarantee. Each test names the
 * property and was mutation-checked: removing the code that provides it makes it fail.
 *
 *  G1 dedupe     a repeated event id never adds a row or replaces the stored event
 *  G2 order      rows appear in first-arrival order; a later update never moves a row
 *  G3 tool pair  one row per tool_call_id, at its first position, showing the latest update
 *  G4 gaps       every "N event(s) dropped" notice becomes its own gap row with its count
 *  G5 total      every displayOrder key resolves to a renderable item
 *  G6 purity     the reducer never mutates the state it is given
 */
import { describe, expect, it } from "vitest";
import {
  getDisplayItems,
  initialSessionViewState,
  mergeHistory,
  reduceSessionEvents,
  sessionReducer,
} from "./session-reducer";
import { AgentEvent, MessageEvent, NotificationEvent, ToolEvent } from "@/types/events";

const base = { timestamp: "t", session_id: "s" };
const msg = (id: string, message = id): MessageEvent => ({ ...base, id, type: "message", role: "assistant", message });
const tool = (id: string, callId: string, status: "calling" | "called", result?: string): ToolEvent => ({
  ...base, id, type: "tool", tool_call_id: callId, tool_name: "bash", function_name: "run",
  function_args: {}, status, result,
});
const dropped = (id: string | undefined, n: number) =>
  ({ ...base, id, type: "notification", text: `${n} event(s) dropped — client fell behind` }) as unknown as NotificationEvent;
const ids = (events: AgentEvent[]) =>
  getDisplayItems(reduceSessionEvents(events)).map((i) => (i.kind === "gap" ? i.key : i.event.id));

describe("G1 dedupe", () => {
  it("a re-delivered id with different content keeps the first and adds no row", () => {
    const state = reduceSessionEvents([msg("a", "first"), msg("a", "second")]);
    expect(state.displayOrder).toEqual(["a"]);
    expect((state.eventsById.get("a") as MessageEvent).message).toBe("first");
  });
  it("replaying a whole history over itself is a no-op", () => {
    const events = [msg("a"), tool("t1", "c", "calling"), tool("t2", "c", "called"), dropped("g", 2)];
    const once = reduceSessionEvents(events);
    expect(events.reduce(sessionReducer, once)).toBe(once);
  });
});

describe("G2 order", () => {
  it("is first-arrival order for any interleaving of kinds", () => {
    expect(ids([msg("b"), tool("t1", "c", "calling"), msg("a"), dropped("g", 1), msg("z")])).toEqual([
      "b", "t1", "a", "g", "z",
    ]);
  });
});

describe("G3 tool pair", () => {
  it("shows the latest update of a call at the call's first position", () => {
    const items = getDisplayItems(
      reduceSessionEvents([tool("t1", "c", "calling"), msg("m"), tool("t2", "c", "called", "out")])
    );
    expect(items.map((i) => (i.kind === "event" ? i.event.id : "gap"))).toEqual(["t2", "m"]);
  });
});

describe("G4 gaps", () => {
  it("each distinct drop notice is its own gap row with its own count", () => {
    const items = getDisplayItems(reduceSessionEvents([dropped("g1", 3), msg("m"), dropped("g2", 5)]));
    expect(items.filter((i) => i.kind === "gap").map((i) => i.kind === "gap" && i.droppedCount)).toEqual([3, 5]);
  });
  it("the backend's SSE drop notice carries no id (sse.py:96-100): successive ones must still all surface", () => {
    const items = getDisplayItems(reduceSessionEvents([dropped(undefined, 3), msg("m"), dropped(undefined, 5)]));
    const gaps = items.filter((i) => i.kind === "gap");
    expect(gaps.map((g) => g.kind === "gap" && g.droppedCount)).toEqual([3, 5]);
    expect(new Set(gaps.map((g) => g.kind === "gap" && g.key)).size).toBe(2);
  });
});

describe("G5 total", () => {
  it("every display key resolves, including gaps and tool rows", () => {
    const state = reduceSessionEvents([msg("a"), tool("t1", "c", "calling"), dropped(undefined, 1), tool("t2", "c", "called")]);
    const items = getDisplayItems(state);
    expect(items).toHaveLength(state.displayOrder.length);
    expect(items.every((i) => i.kind === "gap" || i.event?.id)).toBe(true);
  });
});

describe("G6 purity", () => {
  it("does not mutate the previous state", () => {
    const s0 = reduceSessionEvents([msg("a")]);
    const order = [...s0.displayOrder];
    sessionReducer(s0, msg("b"));
    expect(s0.displayOrder).toEqual(order);
    expect(s0.eventsById.size).toBe(1);
  });
});

describe("mergeHistory", () => {
  it("puts history in server order and keeps client-only rows after it", () => {
    const live = reduceSessionEvents([msg("m3"), { ...msg("opt"), role: "user", delivery: "failed" } as MessageEvent, dropped(undefined, 2)]);
    const merged = mergeHistory(live, [msg("m1"), msg("m2"), msg("m3")]);
    const order = getDisplayItems(merged).map((i) => (i.kind === "gap" ? "gap" : i.event.id));
    expect(order).toEqual(["m1", "m2", "m3", "opt", "gap"]);
    expect((merged.eventsById.get("opt") as MessageEvent).delivery).toBe("failed");
  });
  it("boundary: empty history leaves the live rows as they were", () => {
    const live = reduceSessionEvents([msg("a")]);
    expect(getDisplayItems(mergeHistory(live, []))).toEqual(getDisplayItems(live));
  });
  it("boundary: empty live state yields exactly the history", () => {
    expect(getDisplayItems(mergeHistory(initialSessionViewState, [msg("a"), msg("b")])).length).toBe(2);
  });
});
