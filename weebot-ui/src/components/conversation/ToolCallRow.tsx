import { useEffect, useId, useRef, useState } from "react";
import { AlertCircle, Check, ChevronDown, ChevronRight, Copy, Loader2, Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useIntlContext } from "@/hooks/useIntlContext";
import { formatNumber } from "@/lib/format";
import { useAnnounce } from "@/providers/AnnouncerProvider";
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
  const ctx = useIntlContext();
  const announce = useAnnounce();
  const detailsId = useId();
  const copiedTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(copiedTimer.current), []);
  const isCalling = event.status === "calling";
  const failed = !isCalling && event.is_error === true;
  const args = event.function_args ?? {};
  const hasArgs = Object.keys(args).length > 0;
  const result = event.result ?? "";
  const truncated = !showAll && result.length > RESULT_PREVIEW_CHARS;
  const preview = argsPreview(args);
  // Don't cut a surrogate pair in half: the orphan half renders as U+FFFD.
  const lastCode = result.charCodeAt(RESULT_PREVIEW_CHARS - 1);
  const cut = lastCode >= 0xd800 && lastCode <= 0xdbff ? RESULT_PREVIEW_CHARS - 1 : RESULT_PREVIEW_CHARS;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(result || JSON.stringify(args, null, 2));
      setCopied(true);
      announce("Copied");
      clearTimeout(copiedTimer.current);
      copiedTimer.current = setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      // clipboard blocked (insecure context / permission)
      console.warn("[ToolCallRow] copy failed", e);
      announce("Couldn’t copy");
    }
  };

  return (
    <div className={failed ? "rounded-lg border border-status-error/40 bg-surface-2 text-sm" : "rounded-lg border bg-surface-2 text-sm"}>
      <Button
        variant="ghost"
        onClick={() => setExpanded((e) => !e)}
        className="h-auto w-full justify-start gap-2 rounded-lg px-3 py-2 text-left font-normal hover:bg-surface-3"
        aria-expanded={expanded}
        aria-controls={detailsId}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}
        <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <Badge variant="outline" translate="no" className="shrink-0">
          {event.tool_name}
        </Badge>
        <span translate="no" className="min-w-0 truncate font-mono text-xs text-muted-foreground">
          {preview || event.function_name}
        </span>
        {isCalling ? (
          <Loader2 className="ml-auto h-3.5 w-3.5 shrink-0 motion-safe:animate-spin text-status-live-fg" role="img" aria-label="Running" />
        ) : failed ? (
          <span className="ml-auto flex shrink-0 items-center gap-1 text-xs text-status-error-fg">
            <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
            Failed
          </span>
        ) : (
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">Done</span>
        )}
      </Button>

      {expanded && (
        <div id={detailsId} className="space-y-2 px-3 pb-3">
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
                {truncated ? result.slice(0, cut) : result}
              </pre>
              {truncated && (
                <p className="mt-1 text-xs text-muted-foreground tabular-nums">
                  Showing {formatNumber(cut, ctx)} of {formatNumber(result.length, ctx)} characters.{" "}
                  <button type="button" className="focus-ring rounded-sm underline underline-offset-2" onClick={() => setShowAll(true)}>
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
