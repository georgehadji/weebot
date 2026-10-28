/**
 * Which stream events deserve a screen-reader announcement.
 *
 * The timeline itself is not a live region (every row would be read as it lands); instead only
 * these coarse, meaningful moments are announced through the AnnouncerProvider.
 */
import { AgentEvent, DoneEvent } from "@/types/events";

/** A failed run must not read as done; events without a status predate it and say completed. */
export function doneLabel(event: DoneEvent): string {
  return event.status === "failed" ? "Session failed" : "Session completed";
}

export function announcementFor(event: AgentEvent): string | null {
  switch (event.type) {
    case "step":
      if (event.status === "completed") return `Step completed: ${event.description}`;
      if (event.status === "failed" || event.status === "error") return `Step failed: ${event.description}`;
      return null;
    case "wait_for_user":
      return `Weebot is waiting for your reply: ${event.question}`;
    case "error":
      return `Error: ${event.error}`;
    case "done":
      return doneLabel(event);
    case "tool":
      return event.status === "called" && event.is_error ? `Tool ${event.tool_name} failed` : null;
    default:
      return null;
  }
}
