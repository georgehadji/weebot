import { AlertCircle, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { MessageEvent } from "@/types/events";

interface MessageRowProps {
  event: MessageEvent;
  /** Re-send a message whose delivery failed. */
  onRetry?: (event: MessageEvent) => void;
}

export function MessageRow({ event, onRetry }: MessageRowProps) {
  const isUser = event.role === "user";
  return (
    <div className={cn("flex flex-col gap-1", isUser ? "items-end" : "items-start")}>
      <div
        className={cn(
          "max-w-[70ch] rounded-lg px-3.5 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap",
          isUser
            ? "bg-user text-user-foreground"
            : "bg-agent/10 border border-agent/20 text-foreground",
          event.delivery === "sending" && "opacity-70"
        )}
      >
        {event.message}
      </div>
      {event.delivery === "sending" && (
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          Sending…
        </span>
      )}
      {event.delivery === "failed" && (
        <span className="flex items-center gap-2 text-xs text-status-error-fg">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          Not sent
          {onRetry && (
            <Button variant="outline" size="sm" onClick={() => onRetry(event)} className="gap-1">
              <RotateCcw className="h-3 w-3" aria-hidden="true" />
              Retry
            </Button>
          )}
        </span>
      )}
    </div>
  );
}
