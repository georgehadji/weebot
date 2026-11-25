import { describe, expect, it } from "vitest";
import { applyPresence } from "./useSessionList";
import { Session, SessionPresenceEvent } from "@/types/events";

const session = { id: "s", status: "running", title: "T" } as Session;
const presence = (status: string): SessionPresenceEvent =>
  ({ type: "session_presence", about_session_id: "s", status, title: "" }) as SessionPresenceEvent;

describe("applyPresence", () => {
  it("applies a known status", () => {
    expect(applyPresence(session, presence("completed")).status).toBe("completed");
  });

  it("keeps the loaded status for 'deleted', which is not a session status", () => {
    expect(applyPresence(session, presence("deleted"))).toBe(session);
  });

  const at = (timestamp: string) => ({ ...presence("running"), timestamp }) as SessionPresenceEvent;
  const saved = (updated_at: string) => ({ ...session, status: "failed", updated_at }) as Session;

  it("ignores a frame older than the loaded row", () => {
    const row = saved("2026-10-31T01:00:00Z");
    expect(applyPresence(row, at("2026-10-31T00:30:00Z"))).toBe(row);
  });

  it("applies a frame newer than the loaded row", () => {
    const row = saved("2026-10-31T01:00:00Z");
    expect(applyPresence(row, at("2026-10-31T01:00:01Z")).status).toBe("running");
  });

  it("applies a frame whose time cannot be compared", () => {
    const row = saved("2026-10-31T01:00:00Z");
    expect(applyPresence(row, at("not a time")).status).toBe("running");
  });
});
