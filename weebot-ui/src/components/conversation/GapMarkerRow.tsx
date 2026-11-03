"use client";

import { AlertTriangle } from "lucide-react";
import { useIntlContext } from "@/hooks/useIntlContext";
import { plural } from "@/lib/format";

/** Not a live region: the loss is announced once by `announcementFor` (lib/announce.ts). */
export function GapMarkerRow({ droppedCount }: { droppedCount: number }) {
  const ctx = useIntlContext();
  return (
    <div className="flex items-center justify-center gap-1.5 py-1.5 text-xs text-status-waiting-fg tabular-nums">
      <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span>
        {plural(droppedCount, ctx, { one: "{n} event", other: "{n} events" })} missed — connection fell behind
      </span>
    </div>
  );
}
