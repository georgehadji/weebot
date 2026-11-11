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
});
