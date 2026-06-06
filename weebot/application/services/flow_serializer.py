"""FlowSerializer — converts completed agent flows to visual/export formats.

Produces Mermaid diagrams, JSON execution traces, and LangGraph-compatible
definitions from a :class:`~weebot.domain.models.session.Session` and its
associated :class:`~weebot.domain.models.plan.Plan`.

Pure application-layer service — no infrastructure dependencies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weebot.domain.models.event import AgentEvent
    from weebot.domain.models.plan import Plan
    from weebot.domain.models.session import Session


class FlowSerializer:
    """Serialize completed agent flows to human- and machine-readable formats.

    Usage::

        serializer = FlowSerializer()
        mermaid = serializer.to_mermaid(session, plan)
        trace = serializer.to_json_trace(session, plan, events)
        langgraph = serializer.to_langgraph(session)
    """

    # ── Mermaid ───────────────────────────────────────────────────────

    def to_mermaid(self, session: "Session", plan: "Plan") -> str:
        """Produce a Mermaid ``stateDiagram-v2`` or ``flowchart`` diagram.

        Returns a markdown-fenced Mermaid diagram showing the flow states
        and step transitions with status annotations.
        """
        lines = ["```mermaid", "stateDiagram-v2"]
        lines.append(f"    [*] --> Planning")
        lines.append(f"    Planning --> Executing : plan created")

        for i, step in enumerate(plan.steps):
            step_id = step.id or f"step_{i}"
            status = step.status.value if hasattr(step.status, "value") else str(step.status)
            label = (step.description or step_id)[:40]
            # Sanitize for Mermaid: remove special chars
            label = label.replace('"', "'").replace("\n", " ")
            status_icon = {
                "completed": "✓",
                "failed": "✗",
                "running": "●",
                "pending": "○",
            }.get(status, "?")
            lines.append(f"    Executing --> {step_id} : {status_icon} {label}")
            if status == "completed":
                lines.append(f"    {step_id} --> Executing : done")
            elif status == "failed":
                lines.append(f"    {step_id} --> Updating : failed")

        lines.append(f"    Executing --> Updating : plan needs revision")
        lines.append(f"    Updating --> Executing : plan revised")
        lines.append(f"    Executing --> Summarizing : all steps done")
        lines.append(f"    Summarizing --> [*] : session complete")
        lines.append("```")
        return "\n".join(lines)

    def to_mermaid_flowchart(self, session: "Session", plan: "Plan") -> str:
        """Produce a Mermaid ``flowchart TD`` with richer step detail.

        Preferred for documentation and PR descriptions.
        """
        lines = ["```mermaid", "flowchart TD"]
        session_id = getattr(session, "id", "unknown")[:12]

        lines.append(f"    start[Start: {session_id}] --> plan[Plan]")

        for i, step in enumerate(plan.steps):
            node_id = f"step{i}"
            desc = (step.description or f"Step {i+1}")[:50]
            desc = desc.replace('"', "'").replace("\n", " ").replace("[", "(").replace("]", ")")
            status = step.status.value if hasattr(step.status, "value") else str(step.status)
            style = {
                "completed": ":::completed",
                "failed": ":::failed",
                "running": ":::running",
                "pending": ":::pending",
            }.get(status, "")
            lines.append(f"    {node_id}[\"{desc}\"]{style}")

            if i == 0:
                lines.append(f"    plan --> {node_id}")
            else:
                lines.append(f"    step{i-1} --> {node_id}")

        lines.append(f"    step{len(plan.steps)-1} --> done[Done]")
        lines.append("")

        # CSS classes for styling
        lines.append("    classDef completed fill:#90EE90,stroke:#333,color:#000")
        lines.append("    classDef failed fill:#FFB6C1,stroke:#333,color:#000")
        lines.append("    classDef running fill:#87CEEB,stroke:#333,color:#000")
        lines.append("    classDef pending fill:#E0E0E0,stroke:#333,color:#000")
        lines.append("```")
        return "\n".join(lines)

    # ── JSON Trace ────────────────────────────────────────────────────

    def to_json_trace(
        self,
        session: "Session",
        plan: "Plan",
        events: list["AgentEvent"],
    ) -> dict[str, Any]:
        """Produce a chronological JSON execution trace.

        Returns a dict with:
        - ``session_id``, ``created_at``
        - ``plan``: {steps: [...], status}
        - ``trace``: [{type, timestamp, summary} per event]
        - ``stats``: {total_events, tool_calls, errors, duration_s}
        """
        session_id = getattr(session, "id", "unknown")

        # Plan summary
        plan_data = {
            "status": plan.status.value if hasattr(plan.status, "value") else str(plan.status),
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                    "result": s.result,
                }
                for s in plan.steps
            ],
        }

        # Event trace
        trace = []
        tool_call_count = 0
        error_count = 0
        first_ts: datetime | None = None
        last_ts: datetime | None = None

        for evt in events:
            ts = getattr(evt, "timestamp", None)
            if ts and isinstance(ts, datetime):
                if first_ts is None:
                    first_ts = ts
                last_ts = ts

            entry: dict[str, Any] = {
                "type": getattr(evt, "type", "unknown"),
                "timestamp": ts.isoformat() if ts and isinstance(ts, datetime) else None,
            }

            if hasattr(evt, "message"):
                entry["message"] = getattr(evt, "message", "")[:200]
            if hasattr(evt, "tool_name"):
                entry["tool"] = getattr(evt, "tool_name", "")
                tool_call_count += 1
            if hasattr(evt, "error"):
                entry["error"] = getattr(evt, "error", "")
                error_count += 1
            if hasattr(evt, "step_id"):
                entry["step_id"] = getattr(evt, "step_id", "")
            if hasattr(evt, "thought"):
                entry["thought"] = getattr(evt, "thought", "")[:200]

            trace.append(entry)

        # Stats
        duration_s = 0.0
        if first_ts and last_ts:
            duration_s = (last_ts - first_ts).total_seconds()

        return {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "plan": plan_data,
            "trace": trace,
            "stats": {
                "total_events": len(events),
                "tool_calls": tool_call_count,
                "errors": error_count,
                "duration_s": round(duration_s, 2),
            },
        }

    # ── LangGraph ─────────────────────────────────────────────────────

    def to_langgraph(self, session: "Session") -> dict[str, Any]:
        """Produce a LangGraph-compatible ``StateGraph`` definition.

        Returns a dict that can be passed to ``StateGraph.__init__()`` or
        serialized to JSON for handoff to a LangGraph project.

        Nodes represent flow states; edges represent transitions.  The
        output is a structural definition only — the actual LLM-calling
        logic must be implemented in a LangGraph node function.
        """
        session_id = getattr(session, "id", "unknown")

        nodes = [
            {"id": "planning", "description": "Generate a task plan"},
            {"id": "executing", "description": "Execute plan steps in order"},
            {"id": "updating", "description": "Revise plan based on execution results"},
            {"id": "summarizing", "description": "Produce final summary"},
        ]

        edges = [
            {"from": "planning", "to": "executing"},
            {"from": "executing", "to": "updating", "condition": "step_failed"},
            {"from": "updating", "to": "executing", "condition": "plan_revised"},
            {"from": "executing", "to": "summarizing", "condition": "all_steps_done"},
            {"from": "summarizing", "to": "__end__"},
        ]

        return {
            "session_id": session_id,
            "graph_name": f"PlanActFlow_{session_id[:8]}",
            "nodes": nodes,
            "edges": edges,
            "entry_point": "planning",
            "note": (
                "Structural definition only. Implement node functions "
                "(planning_node, executing_node, updating_node, summarizing_node) "
                "with LLM calls matching weebot's PlannerAgent / ExecutorAgent logic."
            ),
        }
