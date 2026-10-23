import { AlertTriangle, CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { StepEvent } from "@/types/events";

const STATUS_ICON = {
  completed: CheckCircle2,
  running: Loader2,
  started: Loader2,
  error: XCircle,
  failed: XCircle,
  unverified: AlertTriangle,
} as const;

const STATUS_CLASS = {
  completed: "text-status-live",
  running: "text-status-waiting animate-spin",
  started: "text-status-waiting animate-spin",
  error: "text-status-error",
  failed: "text-status-error",
  unverified: "text-status-waiting",
} as const;

export function StepRow({ event }: { event: StepEvent }) {
  const Icon = STATUS_ICON[event.status as keyof typeof STATUS_ICON] ?? Circle;
  const colorClass =
    STATUS_CLASS[event.status as keyof typeof STATUS_CLASS] ?? "text-status-idle";

  return (
    <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
      <Icon className={`h-3.5 w-3.5 shrink-0 ${colorClass}`} />
      <span>{event.description}</span>
    </div>
  );
}
