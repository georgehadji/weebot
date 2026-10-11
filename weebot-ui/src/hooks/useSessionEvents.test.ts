import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AgentEvent } from "@/types/events";
import { useSessionEvents } from "./useSessionEvents";

type Listener = (event: AgentEvent) => void;

const listeners = new Set<Listener>();

vi.mock("@/providers/EventStreamProvider", () => ({
  useEventStreamContext: () => ({
    subscribeSession: (_sessionId: string, listener: Listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSessionMode: () => "websocket",
  }),
}));

const emit = (id: string) => {
  const event = { id, type: "message", session_id: "s1" } as unknown as AgentEvent;
  listeners.forEach((l) => l(event));
};

describe("useSessionEvents", () => {
  it("delivers every event when two arrive before a render", () => {
    // A consumer that accumulates events, like ConversationPane and ToolsTab.
    const { result } = renderHook(() => {
      const [seen, setSeen] = useState<string[]>([]);
      useSessionEvents("s1", (event) => setSeen((prev) => [...prev, event.id]));
      return seen;
    });

    // Both frames land inside one batch. With the old `lastMessage` state
    // the first was overwritten before the consumer's effect could see it.
    act(() => {
      emit("e1");
      emit("e2");
    });

    expect(result.current).toEqual(["e1", "e2"]);
  });

  it("unsubscribes on unmount", () => {
    const onEvent = vi.fn();
    const { unmount } = renderHook(() => useSessionEvents("s1", onEvent));
    unmount();

    emit("after-unmount");

    expect(onEvent).not.toHaveBeenCalled();
  });
});
