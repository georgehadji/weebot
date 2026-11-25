import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Session, SessionPresenceEvent } from "@/types/events";

const h = vi.hoisted(() => ({
  list: vi.fn(),
  presence: new Map<string, SessionPresenceEvent>(),
}));

vi.mock("@/lib/api", () => ({ api: { sessions: { list: h.list } } }));
vi.mock("./useSessionPresence", () => ({ useSessionPresence: () => h.presence }));
vi.mock("@/providers/EventStreamProvider", () => ({ useEventStreamContext: () => ({ streamEpoch: 0 }) }));

import { useSessionList } from "./useSessionList";

const row = { id: "s1", status: "running", title: "T", updated_at: "2026-10-31T05:00:00Z" } as Session;
const frame = (status: string, timestamp: string) =>
  ({ type: "session_presence", about_session_id: "s1", status, title: "", timestamp }) as SessionPresenceEvent;

describe("the rail's settle refetch", () => {
  it("does not reload for a frame the loaded row has outrun", async () => {
    h.list.mockResolvedValue({ sessions: [row] });
    h.presence.set("s1", frame("completed", "2026-10-31T01:00:00Z")); // an earlier run's end
    const { result } = renderHook(() => useSessionList());
    await waitFor(() => expect(result.current.sessions).toHaveLength(1));
    expect(result.current.sessions[0].status).toBe("running");
    expect(h.list).toHaveBeenCalledTimes(1);
  });

  it("reloads once for a settled frame newer than the row", async () => {
    h.list.mockClear();
    h.list.mockResolvedValue({ sessions: [row] });
    h.presence.set("s1", frame("completed", "2026-10-31T06:00:00Z"));
    const { result } = renderHook(() => useSessionList());
    await waitFor(() => expect(h.list).toHaveBeenCalledTimes(2));
    expect(result.current.sessions[0].status).toBe("completed");
  });
});
