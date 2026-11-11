"use client";

import { useEffect, useRef, useState } from "react";
import { Edit3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useIntlContext } from "@/hooks/useIntlContext";
import { plural } from "@/lib/format";
import { PlanReviewEvent } from "@/types/events";

interface PlanReviewCardProps {
  event: PlanReviewEvent;
  onReply?: (text: string) => void | Promise<void>;
  /** Move focus to the composer so the reader can describe what to change. */
  onRequestChanges?: () => void;
}

export function PlanReviewCard({ event, onReply, onRequestChanges }: PlanReviewCardProps) {
  const ctx = useIntlContext();
  const steps = event.plan_data?.steps ?? [];
  // The ref guard stops a double click sending two approvals; once sent, the card is read-only.
  const [approved, setApproved] = useState(false);
  const { run, pending } = useAsyncAction(() => onReply?.("approve"));
  const approvedRef = useRef<HTMLParagraphElement>(null);

  // The button leaves the page on approval; keep keyboard focus on the outcome.
  useEffect(() => {
    if (approved) approvedRef.current?.focus();
  }, [approved]);

  return (
    <Card className="border-primary/35 bg-primary/5">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Edit3 className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <CardTitle className="min-w-0 text-sm font-medium break-words text-foreground">
            Plan ready for review —{" "}
            {plural(event.step_count, ctx, { one: "{n} step", other: "{n} steps" })}
          </CardTitle>
        </div>
        {event.plan_data?.title && (
          <p className="text-xs break-words text-muted-foreground">{event.plan_data.title}</p>
        )}
      </CardHeader>
      <CardContent>
        {/* The list numbers the steps; a typed number as well copied as "1. 1.List". */}
        <ol className="list-decimal space-y-1 pl-6 text-sm marker:text-muted-foreground">
          {steps.map((step) => (
            <li key={step.id} className="min-w-0 break-words">
              {step.description}
            </li>
          ))}
        </ol>
        {approved ? (
          <p ref={approvedRef} tabIndex={-1} className="mt-3 text-sm font-medium outline-hidden">
            Plan approved
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              loading={pending}
              onClick={async () => {
                if (await run()) setApproved(true);
              }}
              disabled={!onReply}
            >
              Approve plan
            </Button>
            <Button size="sm" variant="outline" onClick={onRequestChanges} disabled={!onRequestChanges}>
              Request changes
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
