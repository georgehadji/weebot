"use client";

import { useEffect, useMemo } from "react";
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { AlertTriangle, CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import type { StepStatus } from "@/types/events";

interface PlanStep {
  id: string;
  description: string;
  status: StepStatus;
  dependencies?: string[];
}

interface PlanVisualizerProps {
  steps: PlanStep[];
  title?: string;
}

const nodeTypes = {
  step: StepNode,
};

function StepNode({ data }: NodeProps<{ step: PlanStep; index: number }>) {
  const { step, index } = data;

  const getIcon = () => {
    switch (step.status) {
      case "completed":
        return <CheckCircle2 className="h-5 w-5 text-status-live-fg" />;
      case "running":
      case "started":
        return <Loader2 className="h-5 w-5 text-status-waiting-fg animate-spin" />;
      case "error":
      case "failed":
        return <XCircle className="h-5 w-5 text-status-error-fg" />;
      case "unverified":
        return <AlertTriangle className="h-5 w-5 text-status-waiting-fg" />;
      default:
        return <Circle className="h-5 w-5 text-muted-foreground" />;
    }
  };

  const getBorderColor = () => {
    switch (step.status) {
      case "completed":
        return "border-status-live";
      case "running":
      case "started":
      case "unverified":
        return "border-status-waiting";
      case "error":
      case "failed":
        return "border-status-error";
      default:
        return "border-border-strong";
    }
  };

  return (
    <div
      className={`min-w-[200px] rounded-lg border-2 bg-card px-4 py-3 text-card-foreground shadow-xs ${getBorderColor()}`}
    >
      <div className="flex items-center gap-2">
        {getIcon()}
        <div className="flex-1 min-w-0">
          <div className="text-xs text-muted-foreground">Step {index + 1}</div>
          <div className="text-sm font-medium truncate">{step.description}</div>
        </div>
      </div>
    </div>
  );
}

export function PlanVisualizer({ steps, title }: PlanVisualizerProps) {
  const initialNodes: Node[] = useMemo(
    () =>
      steps.map((step, index) => ({
        id: step.id,
        type: "step",
        position: { x: 250, y: index * 100 },
        data: { step, index },
      })),
    [steps]
  );

  const initialEdges: Edge[] = useMemo(() => {
    const edges: Edge[] = [];
    steps.forEach((step, index) => {
      // Connect to next step by default
      if (index < steps.length - 1) {
        edges.push({
          id: `e${step.id}-${steps[index + 1].id}`,
          source: step.id,
          target: steps[index + 1].id,
          animated: step.status === "running",
          style: {
            stroke:
              step.status === "completed"
                ? "hsl(var(--status-live))"
                : step.status === "running"
                ? "hsl(var(--status-waiting))"
                : "hsl(var(--status-idle))",
          },
        });
      }
      // Connect dependencies
      step.dependencies?.forEach((depId) => {
        edges.push({
          id: `e${depId}-${step.id}`,
          source: depId,
          target: step.id,
          animated: step.status === "running",
        });
      });
    });
    return edges;
  }, [steps]);

  const [nodes, setNodes] = useNodesState(initialNodes);
  // Derived, not state: seeding useEdgesState once froze the edges at the first plan drawn.
  const edges = initialEdges;

  // Update nodes when steps change
  useEffect(() => {
    setNodes(
      steps.map((step, index) => ({
        id: step.id,
        type: "step",
        position: { x: 250, y: index * 100 },
        data: { step, index },
      }))
    );
  }, [steps, setNodes]);

  if (steps.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        No plan steps available
      </div>
    );
  }

  return (
    <div className="h-[500px] border rounded-lg overflow-hidden">
      {title && (
        <div className="px-4 py-2 bg-muted border-b">
          <h3 className="font-medium">{title}</h3>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        fitView
        attributionPosition="bottom-right"
      >
        <Background color="hsl(var(--border))" gap={16} />
        <Controls className="[&>button]:border-border [&>button]:bg-card [&>button]:text-foreground [&>button:hover]:bg-accent" />
        <MiniMap
          nodeColor="hsl(var(--primary))"
          nodeStrokeWidth={3}
          maskColor="hsl(var(--background) / 0.6)"
          style={{ background: "hsl(var(--surface-2))" }}
          zoomable
          pannable
        />
      </ReactFlow>
    </div>
  );
}
