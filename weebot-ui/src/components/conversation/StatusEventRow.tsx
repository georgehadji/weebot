import { AlertCircle, CheckCircle2, HelpCircle, ShieldCheck, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { doneLabel } from "@/lib/announce";
import {
  DoneEvent,
  ErrorEvent,
  NotificationEvent,
  ToolApprovalEvent,
  WaitForUserEvent,
} from "@/types/events";

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
      <HelpCircle className="h-4 w-4 shrink-0 mt-0.5 text-status-waiting-fg" aria-hidden="true" />
      <p className="text-sm whitespace-pre-wrap">{event.question}</p>
    </div>
  );
}

export function ToolApprovalRow({
  event,
  onReply,
}: {
  event: ToolApprovalEvent;
  onReply?: (text: string) => void;
}) {
  // The backend prompt also serves the CLI, where typing yes/no is necessary. In the web UI
  // the controls below replace that final instruction, so avoid telling the operator to type.
  const prompt = event.prompt
    .replace(/\s*Reply ['"]yes['"] to run this exact call once, or say what to do instead\.?\s*$/i, "")
    .trim();
  return (
    <div className="surface-waiting rounded-lg border p-3" role="group" aria-label="Approval request">
      <div className="flex items-start gap-2">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-status-waiting-fg" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm font-medium">Approval needed: {event.tool_name}</p>
          {prompt && <p className="mt-1 whitespace-pre-wrap text-sm">{prompt}</p>}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => onReply?.("approve")} disabled={!onReply}>
          Approve once
        </Button>
        {event.allow_always && (
          <Button size="sm" variant="secondary" onClick={() => onReply?.("always")} disabled={!onReply}>
            Always allow {event.allow_always}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => onReply?.("no")} disabled={!onReply}>
          Decline
        </Button>
      </div>
    </div>
  );
}

export function DoneRow({ event }: { event: DoneEvent }) {
  const failed = event.status === "failed";
  const Icon = failed ? XCircle : CheckCircle2;
  return (
    <div className="flex items-center justify-center gap-1.5 py-2 text-xs text-muted-foreground">
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      <Badge variant={failed ? "destructive" : "secondary"}>{doneLabel(event)}</Badge>
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
