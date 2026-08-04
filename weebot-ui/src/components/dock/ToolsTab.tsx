"use client";

import { useEffect, useState } from "react";
import { Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import { AgentEvent, ToolEvent } from "@/types/events";

interface ToolsTabProps {
  sessionId: string;
}

export function ToolsTab({ sessionId }: ToolsTabProps) {
  const { lastMessage } = useSessionEvents(sessionId);
  const [calls, setCalls] = useState<Map<string, ToolEvent>>(new Map());

  useEffect(() => {
    if (lastMessage?.type === "tool") {
      const event = lastMessage as ToolEvent;
      setCalls((prev) => new Map(prev).set(event.tool_call_id, event));
    }
  }, [lastMessage]);

  const entries = Array.from(calls.values()).reverse();

  if (entries.length === 0) {
    return <p className="p-4 text-xs text-muted-foreground">No tool calls yet.</p>;
  }

  return (
    <div className="space-y-1.5 p-2">
      {entries.map((call) => (
        <div key={call.tool_call_id} className="flex items-center gap-2 rounded-md border bg-surface-1 px-2.5 py-1.5 text-xs">
          <Terminal className="h-3 w-3 shrink-0 text-muted-foreground" />
          <Badge variant="outline" className="shrink-0">{call.tool_name}</Badge>
          <span className="truncate font-mono text-muted-foreground">{call.function_name}</span>
          <span className="ml-auto shrink-0 text-muted-foreground">
            {call.status === "calling" ? "running…" : "done"}
          </span>
        </div>
      ))}
    </div>
  );
}
