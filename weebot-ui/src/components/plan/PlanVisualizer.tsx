"use client";

import { useCallback, useMemo } from "react";
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";

interface PlanStep {
  id: string;
  description: string;
  status: "pending" | "running" | "completed" | "error";
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
        return <CheckCircle2 className="h-5 w-5 text-green-500" />;
      case "running":
        return <Loader2 className="h-5 w-5 text-yellow-500 animate-spin" />;
      case "error":
        return <XCircle className="h-5 w-5 text-red-500" />;
      default:
        return <Circle className="h-5 w-5 text-gray-400" />;
    }
  };

  const getBorderColor = () => {
    switch (step.status) {
      case "completed":
        return "border-green-500";
      case "running":
        return "border-yellow-500";
      case "error":
        return "border-red-500";
      default:
        return "border-gray-300";
    }
  };

  return (
    <div
      className={`px-4 py-3 rounded-lg border-2 bg-white shadow-sm min-w-[200px] ${getBorderColor()}`}
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
                ? "#22c55e"
                : step.status === "running"
                ? "#eab308"
                : "#9ca3af",
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

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (params: any) => setEdges((eds) => [...eds, params]),
    [setEdges]
  );

  // Update nodes when steps change
  useMemo(() => {
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
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-right"
      >
        <Background />
        <Controls />
        <MiniMap
          nodeStrokeWidth={3}
          zoomable
          pannable
        />
      </ReactFlow>
    </div>
  );
}
