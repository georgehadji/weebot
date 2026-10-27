"use client";

import { Circle, Edit3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PlanReviewEvent } from "@/types/events";

interface PlanReviewCardProps {
  event: PlanReviewEvent;
}

export function PlanReviewCard({ event }: PlanReviewCardProps) {
  const steps = event.plan_data?.steps ?? [];

  return (
    <Card className="border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Edit3 className="h-4 w-4 text-blue-600" />
          <CardTitle className="text-sm font-medium text-blue-800 dark:text-blue-200">
            Plan ready for review —{" "}
            {event.step_count} step{event.step_count !== 1 ? "s" : ""}
          </CardTitle>
        </div>
        {event.plan_data?.title && (
          <p className="text-xs text-muted-foreground">{event.plan_data.title}</p>
        )}
      </CardHeader>
      <CardContent>
        {/* The list numbers the steps; a typed number as well copied as "1. 1.List". */}
        <ol className="list-decimal space-y-1 pl-6 text-sm marker:text-muted-foreground">
          {steps.map((step) => (
            <li key={step.id}>
              <span className="inline-flex items-start gap-2">
                <Circle className="h-3 w-3 mt-1 shrink-0 text-blue-400" aria-hidden="true" />
                <span>{step.description}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-muted-foreground italic">
          Type{" "}
          <Badge variant="outline" className="text-xs px-1 py-0">
            approve
          </Badge>{" "}
          below to start execution, or describe any changes needed.
        </p>
      </CardContent>
    </Card>
  );
}
