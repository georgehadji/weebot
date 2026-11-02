"use client";

/**
 * PlanTab — auto-bound to the current session (no manual session-ID box).
 * Replaces the old Dashboard's "Enter a session ID to visualize its plan"
 * input, which made you paste an ID by hand even though you were already
 * looking at that exact session.
 */

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { PlanChecklist } from "@/components/plan/PlanChecklist";
import { api } from "@/lib/api";
import { useSessionEvents } from "@/hooks/useSessionEvents";
import type { PlanEvent, StepEvent, StepStatus } from "@/types/events";

interface PlanTabProps {
  sessionId: string;
}

type Nodes = { id: string; description: string; status: StepStatus }[];

/** The steps of a `plan` event's payload, or null when it carries none. */
function stepsOf(plan: unknown): Nodes | null {
  const steps = (plan as { steps?: unknown } | null | undefined)?.steps;
  if (!Array.isArray(steps)) return null;
  return steps.map((s) => ({
    id: String(s.id),
    description: String(s.description ?? s.id),
    status: (s.status as StepStatus) || "pending",
  }));
}

export function PlanTab({ sessionId }: PlanTabProps) {
  const [nodes, setNodes] = useState<Nodes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // The plan is fetched once, so the run's own events keep it current: a plan event carries the
  // whole (re)planned plan and a step event carries one step's new status.
  useSessionEvents(sessionId, (event) => {
    if (event.type === "plan") {
      const next = stepsOf((event as PlanEvent).plan);
      if (next) setNodes(next);
    } else if (event.type === "step") {
      const { step_id, status } = event as StepEvent;
      setNodes((prev) => prev?.map((n) => (n.id === step_id ? { ...n, status } : n)) ?? prev);
    }
  });

  useEffect(() => {
    let cancelled = false;
    api.ops
      .planViz(sessionId)
      .then((result) => {
        if (cancelled) return;
        if (result.ok) {
          const plan = result.data.plan;
          setNodes(
            (plan?.nodes ?? []).map((n) => ({
              id: n.id,
              description: n.label,
              status: (n.status as StepStatus) || "pending",
            }))
          );
        }
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load plan");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center py-8">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return <p className="p-4 text-xs text-status-error-fg">{error}</p>;
  }

  if (!nodes || nodes.length === 0) {
    return (
      <p className="p-4 text-xs text-muted-foreground">
        No plan yet — this session hasn&apos;t entered planning.
      </p>
    );
  }

  return <PlanChecklist steps={nodes} />;
}
