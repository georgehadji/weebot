/**
 * X6 wiring: the real EventStreamProvider and useSessionEvents drive the real pane.
 * A socket that drops and reopens while the run is still going must pull in the events
 * published during the gap. Only the REST history, the composer and the announcer are stubbed.
 */
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentEvent } from "@/types/events";
import { EventStreamProvider } from "@/providers/EventStreamProvider";
import {
  FakeWebSocketControl,
  installFakeWebSocket,
} from "../../../tests/harness/fake-transport";

const h = vi.hoisted(() => ({ history: [] as unknown[] }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { sessions: { events: () => Promise.resolve(h.history) } } };
});
vi.mock("@/providers/AnnouncerProvider", () => ({ useAnnounce: () => vi.fn() }));
vi.mock("./Composer", () => ({ Composer: () => null }));
vi.mock("./RunControls", () => ({ RunControls: () => null }));

import { ConversationPane } from "./ConversationPane";

const msg = (id: string, text: string): AgentEvent =>
  ({ id, type: "message", role: "assistant", message: text, timestamp: "t", session_id: "s1" }) as AgentEvent;

describe("X6: ConversationPane recovers events missed while the socket was down", () => {
  let sockets: FakeWebSocketControl;

  beforeEach(() => {
    vi.useFakeTimers();
    sockets = installFakeWebSocket();
  });
  afterEach(() => {
    sockets.restore();
    vi.useRealTimers();
  });

  it("shows a step published during the gap once the socket reopens, with the run still running", async () => {
    const { container } = render(
      <EventStreamProvider>
        <ConversationPane sessionId="s1" status="running" onSessionCreated={() => {}} />
      </EventStreamProvider>
    );
    const socket = () => sockets.sockets.filter((ws) => ws.url.includes("s1")).at(-1)!;
    await act(async () => socket().accept());

    await act(async () => {
      socket().serverClose();
      await vi.advanceTimersByTimeAsync(1_000);
    });
    h.history = [msg("gap", "published while the socket was down")];
    await act(async () => socket().accept());

    await vi.waitFor(() =>
      expect(container.querySelector('[role="log"]')?.textContent).toContain(
        "published while the socket was down"
      )
    );
  });
});
