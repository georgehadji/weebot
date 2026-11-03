"use client";

import { useReducer } from "react";
import { AlertCircle, Loader2, Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { ToolEvent } from "@/types/events";

interface ToolsTabProps {
  sessionId: string;
}

/**
 * Newest call first. A new call goes on the front and a later event for the same call replaces
 * it in place, so the list is already in display order (no Map clone, no reverse per render).
 *
 * shortcut: the lookup is a linear scan; swap it for the reducer's tool-call index if lists
 * ever get long enough to matter.
 */
function upsertCall(calls: ToolEvent[], event: ToolEvent): ToolEvent[] {
  const at = calls.findIndex((c) => c.tool_call_id === event.tool_call_id);
  if (at === -1) return [event, ...calls];
  const next = calls.slice();
  next[at] = event;
  return next;
}

export function ToolsTab({ sessionId }: ToolsTabProps) {
  const [calls, upsert] = useReducer(upsertCall, []);
  // Failures are announced by announcementFor's `tool` case; this list is not a live region.
  useSessionEvents(sessionId, (event) => {
    if (event.type === "tool") upsert(event as ToolEvent);
  });

  if (calls.length === 0) {
    return <p className="p-4 text-xs text-muted-foreground">No tool calls yet.</p>;
  }

  return (
    <ul className="space-y-1.5 p-2">
      {calls.map((call) => (
        <li
          key={call.tool_call_id}
          className="cv-auto flex items-center gap-2 rounded-md border bg-surface-1 px-2.5 py-1.5 text-xs"
        >
          <Terminal className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
          <Badge variant="outline" translate="no" title={call.tool_name} className="max-w-[40%] min-w-0 shrink truncate">
            {call.tool_name}
          </Badge>
          <span translate="no" title={call.function_name} className="min-w-0 truncate font-mono text-muted-foreground">
            {call.function_name}
          </span>
          <ToolCallState call={call} />
        </li>
      ))}
    </ul>
  );
}

/** Same states and wording as the timeline's ToolCallRow: Running, Failed, Done. */
function ToolCallState({ call }: { call: ToolEvent }) {
  if (call.status === "calling") {
    return (
      <span className="ml-auto flex shrink-0 items-center gap-1 text-status-live-fg">
        <Loader2 className="h-3 w-3 motion-safe:animate-spin" aria-hidden="true" />
        Running
      </span>
    );
  }
  if (call.is_error === true) {
    return (
      <span className="ml-auto flex shrink-0 items-center gap-1 text-status-error-fg">
        <AlertCircle className="h-3 w-3" aria-hidden="true" />
        Failed
      </span>
    );
  }
  return <span className="ml-auto shrink-0 text-muted-foreground">Done</span>;
}
