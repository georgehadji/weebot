import { cn } from "@/lib/utils";
import { MessageEvent } from "@/types/events";

export function MessageRow({ event }: { event: MessageEvent }) {
  const isUser = event.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[70ch] rounded-lg px-3.5 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap",
          isUser
            ? "bg-user text-user-foreground"
            : "bg-agent/10 border border-agent/20 text-foreground"
        )}
      >
        {event.message}
      </div>
    </div>
  );
}
