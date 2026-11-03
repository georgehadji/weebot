import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, HelpCircle, ShieldCheck, XCircle } from "lucide-react";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAsyncAction } from "@/hooks/useAsyncAction";
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
      <span className="min-w-0 break-words">{event.error}</span>
    </div>
  );
}

export function WaitForUserRow({ event }: { event: WaitForUserEvent }) {
  return (
    <div className="surface-waiting flex items-start gap-2 rounded-lg border p-3">
      <HelpCircle className="h-4 w-4 shrink-0 mt-0.5 text-status-waiting-fg" aria-hidden="true" />
      <p className="min-w-0 text-sm break-words whitespace-pre-wrap">{event.question}</p>
    </div>
  );
}

type Choice = "approve" | "always" | "no";

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
  // The answer is the user's, so there is no confirm for Approve once or Decline (only Always
  // allow, which lasts). They get the double-click guard and, once sent, a resolved line that
  // replaces the buttons. The ref guard also covers a second click in the same tick.
  const [choice, setChoice] = useState<Choice | null>(null);
  const [clicked, setClicked] = useState<Choice | null>(null);
  const [confirmingAlways, setConfirmingAlways] = useState(false);
  const { run, pending } = useAsyncAction((text: Choice) => onReply?.(text));
  const resolvedRef = useRef<HTMLParagraphElement>(null);

  const answer = async (text: Choice) => {
    setClicked(text);
    if (await run(text)) setChoice(text);
  };

  // The button that was pressed leaves the page; keep keyboard focus on the outcome.
  useEffect(() => {
    if (choice) resolvedRef.current?.focus();
  }, [choice]);

  const resolved =
    choice === "approve"
      ? "Approved"
      : choice === "no"
      ? "Declined"
      : choice === "always"
      ? `Always allowed: ${event.tool_name}`
      : null;
  const busy = (c: Choice) => pending && clicked === c;

  return (
    <div className="surface-waiting rounded-lg border p-3" role="group" aria-label="Approval request">
      <div className="flex items-start gap-2">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-status-waiting-fg" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm font-medium break-words">
            Approval needed: <span translate="no">{event.tool_name}</span>
          </p>
          {prompt && <p className="mt-1 text-sm break-words whitespace-pre-wrap">{prompt}</p>}
        </div>
      </div>
      {resolved ? (
        <p ref={resolvedRef} tabIndex={-1} className="mt-3 text-sm font-medium outline-hidden" translate="no">
          {resolved}
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" loading={busy("approve")} onClick={() => answer("approve")} disabled={!onReply}>
            Approve once
          </Button>
          {event.allow_always && (
            <Button
              size="sm"
              variant="secondary"
              loading={busy("always")}
              onClick={() => setConfirmingAlways(true)}
              disabled={!onReply}
            >
              Always allow <span translate="no">{event.allow_always}</span>
            </Button>
          )}
          <Button size="sm" variant="outline" loading={busy("no")} onClick={() => answer("no")} disabled={!onReply}>
            Decline
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={confirmingAlways}
        onOpenChange={setConfirmingAlways}
        title={`Always allow ${event.tool_name}?`}
        description={`Weebot will stop asking before ${event.tool_name} uses ${event.allow_always}. This lasts beyond this session.`}
        confirmLabel="Always allow"
        onConfirm={() => answer("always")}
      />
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
