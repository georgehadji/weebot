"use client";

/**
 * PlanTab — auto-bound to the current session (no manual session-ID box).
 * Replaces the old Dashboard's "Enter a session ID to visualize its plan"
 * input, which made you paste an ID by hand even though you were already
 * looking at that exact session.
 */

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { PlanVisualizer } from "@/components/plan/PlanVisualizer";
import { api } from "@/lib/api";

interface PlanTabProps {
  sessionId: string;
}

export function PlanTab({ sessionId }: PlanTabProps) {
  const [nodes, setNodes] = useState<
    { id: string; description: string; status: "pending" | "running" | "completed" | "error" }[] | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.ops
      .planViz(sessionId)
      .then((result) => {
        if (cancelled) return;
        if (result.ok) {
          setNodes(
            result.data.nodes.map((n) => ({
              id: n.id,
              description: n.label,
              status: (n.status as "pending" | "running" | "completed" | "error") || "pending",
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
    return <p className="p-4 text-xs text-status-error">{error}</p>;
  }

  if (!nodes || nodes.length === 0) {
    return (
      <p className="p-4 text-xs text-muted-foreground">
        No plan yet — this session hasn&apos;t entered planning.
      </p>
    );
  }

  return (
    <div className="p-2">
      <PlanVisualizer steps={nodes} />
    </div>
  );
}
