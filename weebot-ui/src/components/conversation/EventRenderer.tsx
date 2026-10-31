/**
 * EventRenderer — dispatches an AgentEvent to its row component via a
 * type → component registry, replacing the growing switch statement the
 * old session page's EventCard had. Adding a new event type means adding
 * one registry entry, not editing a shared switch (open/closed principle).
 */
import { memo } from "react";
import { AgentEvent, MessageEvent } from "@/types/events";
import { MessageRow } from "./MessageRow";
import { ToolCallRow } from "./ToolCallRow";
import { StepRow } from "./StepRow";
import { PlanReviewCard } from "@/components/PlanReviewCard";
import { ErrorRow, WaitForUserRow, DoneRow, NotificationRow } from "./StatusEventRow";

// A dispatch registry is inherently heterogeneous — each entry's component
// expects a narrower event subtype than AgentEvent, which TypeScript can't
// verify is safe at the map-literal level (function parameters are
// contravariant). The registry is keyed by `event.type`, so each lookup is
// guaranteed to hand the component the exact subtype it declared; `unknown`
// documents that this file — not each row component — owns that guarantee.
type RowComponent = (props: {
  event: never;
  onRetry?: (event: MessageEvent) => void;
}) => React.ReactElement | null;

const EVENT_REGISTRY: Partial<Record<AgentEvent["type"], RowComponent>> = {
  message: MessageRow,
  tool: ToolCallRow,
  step: StepRow,
  plan_review: PlanReviewCard,
  error: ErrorRow,
  wait_for_user: WaitForUserRow,
  done: DoneRow,
  notification: NotificationRow,
} as unknown as Partial<Record<AgentEvent["type"], RowComponent>>;

/** Whether the registry draws anything for this event (the rest are deliberately not rows). */
export const isRendered = (event: AgentEvent) => event.type in EVENT_REGISTRY;

function EventRendererImpl({
  event,
  onRetry,
}: {
  event: AgentEvent;
  /** Re-send a user message whose delivery failed (used by message rows only). */
  onRetry?: (event: MessageEvent) => void;
}) {
  const Row = EVENT_REGISTRY[event.type];
  if (!Row) return null;
  return <Row event={event as never} onRetry={onRetry} />;
}

/**
 * Memoised: the session reducer keeps event objects stable, so appending one event re-renders
 * one row instead of the whole timeline.
 */
export const EventRenderer = memo(EventRendererImpl);
