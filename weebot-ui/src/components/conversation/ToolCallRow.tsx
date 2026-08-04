import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ToolEvent } from "@/types/events";

export function ToolCallRow({ event }: { event: ToolEvent }) {
  const [expanded, setExpanded] = useState(false);
  const isCalling = event.status === "calling";

  return (
    <div className="rounded-lg border bg-surface-2 text-sm">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-3 transition-colors rounded-lg"
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
        <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <Badge variant="outline" className="shrink-0">
          {event.tool_name}
        </Badge>
        <span className="font-mono text-xs text-muted-foreground truncate">
          {event.function_name}
        </span>
        {isCalling ? (
          <Loader2 className="h-3.5 w-3.5 ml-auto shrink-0 animate-spin text-status-live" />
        ) : (
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">done</span>
        )}
      </button>
      {expanded && event.result && (
        <pre className="mx-3 mb-3 max-h-64 overflow-auto rounded bg-surface-1 p-2 font-mono text-xs">
          {event.result.slice(0, 4000)}
          {event.result.length > 4000 && "\n… truncated"}
        </pre>
      )}
    </div>
  );
}
