import { StatusBadge } from "@/components/common/StatusBadge";
import { cn } from "@/lib/utils";
import type { StepStatus } from "@/types/events";

export interface ChecklistStep {
  id: string;
  description: string;
  status: StepStatus;
}

const RUNNING: StepStatus[] = ["running", "started"];

/**
 * PlanChecklist — a session's plan as a plain numbered list.
 *
 * The plan is a sequence, so a list shows it with the whole step text and no layout to read.
 * The diagram it replaces in the dock clipped every step to one line and let its mini-map sit on
 * top of the last steps. The diagram is still used on the Ops page.
 */
export function PlanChecklist({ steps }: { steps: ChecklistStep[] }) {
  const done = steps.filter((s) => s.status === "completed").length;
  const currentId = steps.find((s) => RUNNING.includes(s.status))?.id;

  return (
    <div className="space-y-3 p-3">
      <div className="space-y-1.5">
        <p className="text-xs font-medium tabular-nums text-muted-foreground">{`${done} of ${steps.length} done`}</p>
        {/* Read on demand; the per-step "Step completed" announcements already cover live updates. */}
        <div
          role="progressbar"
          aria-label="Plan progress"
          aria-valuemin={0}
          aria-valuemax={steps.length}
          aria-valuenow={done}
          aria-valuetext={`${done} of ${steps.length} done`}
          className="h-1 overflow-hidden rounded-full bg-surface-2"
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] motion-reduce:transition-none"
            style={{ width: `${steps.length ? (done / steps.length) * 100 : 0}%` }}
          />
        </div>
      </div>
      <ol className="space-y-1.5">
        {steps.map((step, i) => (
          <li
            key={step.id}
            aria-current={step.id === currentId ? "step" : undefined}
            className={cn(
              "flex items-start gap-2.5 rounded-md border bg-surface-1 px-2.5 py-2",
              step.id === currentId && "border-primary",
            )}
          >
            <span className="mt-px w-4 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
              {i + 1}
            </span>
            <StatusBadge status={step.status} variant="icon" className="mt-0.5" />
            <span
              className={cn(
                "min-w-0 flex-1 break-words text-sm leading-snug",
                step.status === "completed" && "text-muted-foreground",
              )}
            >
              {step.description}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
