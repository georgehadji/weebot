"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * PlanVisualizer pulls in reactflow, which only the plan view needs. Loading it on demand keeps
 * it out of the first-load JavaScript of every route that merely *can* show a plan.
 */
export const LazyPlanVisualizer = dynamic(
  () => import("./PlanVisualizer").then((m) => m.PlanVisualizer),
  { ssr: false, loading: () => <Skeleton className="h-48 w-full" aria-label="Loading plan" /> }
);
