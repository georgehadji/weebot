import { AlertTriangle } from "lucide-react";

export function GapMarkerRow({ droppedCount }: { droppedCount: number }) {
  return (
    <div className="flex items-center justify-center gap-1.5 py-1.5 text-xs text-status-waiting">
      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
      <span>
        {droppedCount} event{droppedCount !== 1 ? "s" : ""} missed — connection fell behind
      </span>
    </div>
  );
}
