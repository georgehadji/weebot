import { useState } from "react";
import { AlertCircle, Check, ChevronDown, ChevronRight, Copy, Loader2, Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ToolEvent } from "@/types/events";

const RESULT_PREVIEW_CHARS = 4000;

/** One-line summary of a call's arguments, for the collapsed row. */
function argsPreview(args: Record<string, unknown>): string {
  const first = Object.entries(args)[0];
  if (!first) return "";
  const [key, value] = first;
  return `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`;
}

export function ToolCallRow({ event }: { event: ToolEvent }) {
  const [expanded, setExpanded] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [copied, setCopied] = useState(false);
  const isCalling = event.status === "calling";
  const failed = !isCalling && event.is_error === true;
  const args = event.function_args ?? {};
  const hasArgs = Object.keys(args).length > 0;
  const result = event.result ?? "";
  const truncated = !showAll && result.length > RESULT_PREVIEW_CHARS;
  const preview = argsPreview(args);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(result || JSON.stringify(args, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked (insecure context / permission): nothing useful to tell the user
    }
  };

  return (
    <div className={failed ? "rounded-lg border border-status-error/40 bg-surface-2 text-sm" : "rounded-lg border bg-surface-2 text-sm"}>
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors hover:bg-surface-3"
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}
        <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <Badge variant="outline" className="shrink-0">
          {event.tool_name}
        </Badge>
        <span className="truncate font-mono text-xs text-muted-foreground">
          {preview || event.function_name}
        </span>
        {isCalling ? (
          <Loader2 className="ml-auto h-3.5 w-3.5 shrink-0 animate-spin text-status-live-fg" aria-label="Running" />
        ) : failed ? (
          <span className="ml-auto flex shrink-0 items-center gap-1 text-xs text-status-error-fg">
            <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
            Failed
          </span>
        ) : (
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">Done</span>
        )}
      </button>

      {expanded && (
        <div className="space-y-2 px-3 pb-3">
          {hasArgs && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Arguments</p>
              <pre
                tabIndex={0}
                aria-label="Tool arguments"
                className="max-h-48 overflow-auto rounded bg-surface-1 p-2 font-mono text-xs"
              >
                {JSON.stringify(args, null, 2)}
              </pre>
            </div>
          )}
          {result && (
            <div>
              <div className="mb-1 flex items-center justify-between">
                <p className="text-xs font-medium text-muted-foreground">Result</p>
                <Button variant="ghost" size="sm" onClick={copy} className="gap-1 text-xs">
                  {copied ? <Check className="h-3 w-3" aria-hidden="true" /> : <Copy className="h-3 w-3" aria-hidden="true" />}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
              <pre
                tabIndex={0}
                aria-label="Tool result"
                className="max-h-64 overflow-auto rounded bg-surface-1 p-2 font-mono text-xs"
              >
                {truncated ? result.slice(0, RESULT_PREVIEW_CHARS) : result}
              </pre>
              {truncated && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Showing {RESULT_PREVIEW_CHARS.toLocaleString()} of {result.length.toLocaleString()} characters.{" "}
                  <button className="underline underline-offset-2" onClick={() => setShowAll(true)}>
                    Show all
                  </button>
                </p>
              )}
            </div>
          )}
          {!hasArgs && !result && (
            <p className="text-xs text-muted-foreground">{isCalling ? "Waiting for the result…" : "No output."}</p>
          )}
        </div>
      )}
    </div>
  );
}
