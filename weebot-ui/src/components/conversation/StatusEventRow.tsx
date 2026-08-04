import { AlertCircle, CheckCircle2, HelpCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { DoneEvent, ErrorEvent, NotificationEvent, WaitForUserEvent } from "@/types/events";

export function ErrorRow({ event }: { event: ErrorEvent }) {
  return (
    <div className="surface-error flex items-center gap-2 rounded-lg border p-3 text-sm">
      <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{event.error}</span>
    </div>
  );
}

export function WaitForUserRow({ event }: { event: WaitForUserEvent }) {
  return (
    <div className="surface-waiting flex items-start gap-2 rounded-lg border p-3">
      <HelpCircle className="h-4 w-4 shrink-0 mt-0.5 text-status-waiting" aria-hidden="true" />
      <p className="text-sm whitespace-pre-wrap">{event.question}</p>
    </div>
  );
}

export function DoneRow({}: { event: DoneEvent }) {
  return (
    <div className="flex items-center justify-center gap-1.5 py-2 text-xs text-muted-foreground">
      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
      <Badge variant="secondary">Session completed</Badge>
    </div>
  );
}

export function NotificationRow({ event }: { event: NotificationEvent }) {
  return (
    <div className="flex justify-center py-1">
      <span className="text-xs text-muted-foreground italic">{event.text}</span>
    </div>
  );
}
