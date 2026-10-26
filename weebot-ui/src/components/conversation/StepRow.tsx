import { StatusBadge } from "@/components/common/StatusBadge";
import { StepEvent } from "@/types/events";

export function StepRow({ event }: { event: StepEvent }) {
  return (
    <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
      <StatusBadge status={event.status} variant="icon" />
      <span>{event.description}</span>
    </div>
  );
}
