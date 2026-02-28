"""PlanningTool + PlanningFlow — multi-step plan generation and execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ConfigDict, PrivateAttr

from weebot.core.tool_agent import ToolCallWeebotAgent
from weebot.tools.base import BaseTool, ToolCollection, ToolResult

PLANNING_SYSTEM_PROMPT = """You are weebot, an autonomous AI agent for Windows 11.
When given a task, break it into clear steps using the 'planning' tool, then execute
each step with the available tools, updating step status as you go.
When all steps are complete, provide a clear summary of what was accomplished.
"""


# ---------------------------------------------------------------------------
# Internal plan dataclasses
# ---------------------------------------------------------------------------

_STEP_ICONS: dict[str, str] = {
    "pending": "[ ]",
    "running": "[~]",
    "completed": "[x]",
    "failed": "[!]",
}


@dataclass
class _PlanStep:
    description: str
    status: str = "pending"  # pending | running | completed | failed


@dataclass
class _Plan:
    plan_id: str
    title: str
    steps: list[_PlanStep] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PlanningTool — in-memory plan CRUD
# ---------------------------------------------------------------------------


class PlanningTool(BaseTool):
    """
    In-memory CRUD tool for agent plans.

    Commands:
      create      — create a new plan with a list of steps
      update_step — change a step's status (pending/running/completed/failed)
      get         — display the current plan
      clear       — delete a plan
    """

    name: str = "planning"
    description: str = (
        "Manage a task plan. "
        "Commands: create (new plan + steps), update_step (mark step status), "
        "get (view plan), clear (delete plan)."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["create", "update_step", "get", "clear"],
                "description": "Operation to perform",
            },
            "plan_id": {
                "type": "string",
                "description": "Unique identifier for the plan",
            },
            "title": {
                "type": "string",
                "description": "Plan title (required for 'create')",
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Step descriptions (required for 'create')",
            },
            "step_index": {
                "type": "integer",
                "description": "0-based step index (required for 'update_step')",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "running", "completed", "failed"],
                "description": "New step status (required for 'update_step')",
            },
        },
        "required": ["command", "plan_id"],
    }

    model_config = ConfigDict(arbitrary_types_allowed=True)
    _plans: dict[str, _Plan] = PrivateAttr(default_factory=dict)

    async def execute(self, command: str, plan_id: str, **kwargs: Any) -> ToolResult:
        if command == "create":
            return self._create(
                plan_id,
                kwargs.get("title", ""),
                kwargs.get("steps", []),
            )
        elif command == "update_step":
            return self._update_step(
                plan_id,
                int(kwargs.get("step_index", 0)),
                kwargs.get("status", "completed"),
            )
        elif command == "get":
            return self._get(plan_id)
        elif command == "clear":
            self._plans.pop(plan_id, None)
            return ToolResult(output=f"Plan {plan_id!r} cleared")
        return ToolResult(output="", error=f"Unknown command: {command!r}")

    # ------------------------------------------------------------------
    def _create(self, plan_id: str, title: str, steps: list[str]) -> ToolResult:
        plan = _Plan(
            plan_id=plan_id,
            title=title,
            steps=[_PlanStep(description=s) for s in steps],
        )
        self._plans[plan_id] = plan
        lines = [f"Plan created: {title}", "Steps:"]
        for i, step in enumerate(plan.steps):
            lines.append(f"  {i}. {_STEP_ICONS['pending']} {step.description}")
        return ToolResult(output="\n".join(lines))

    def _update_step(self, plan_id: str, step_index: int, status: str) -> ToolResult:
        if plan_id not in self._plans:
            return ToolResult(output="", error=f"Plan not found: {plan_id!r}")
        plan = self._plans[plan_id]
        if step_index < 0 or step_index >= len(plan.steps):
            return ToolResult(
                output="",
                error=f"Step index {step_index} out of range (plan has {len(plan.steps)} steps)",
            )
        plan.steps[step_index].status = status
        return ToolResult(output=f"Step {step_index} → {status}")

    def _get(self, plan_id: str) -> ToolResult:
        if plan_id not in self._plans:
            return ToolResult(output="", error=f"Plan not found: {plan_id!r}")
        plan = self._plans[plan_id]
        lines = [f"Plan: {plan.title}"]
        for i, step in enumerate(plan.steps):
            icon = _STEP_ICONS.get(step.status, "[ ]")
            lines.append(f"  {i}. {icon} {step.description}")
        return ToolResult(output="\n".join(lines))


# ---------------------------------------------------------------------------
# PlanningFlow — orchestrates ToolCallWeebotAgent with PlanningTool
# ---------------------------------------------------------------------------


class PlanningFlow:
    """
    High-level flow: creates a ToolCallWeebotAgent that has access to
    PlanningTool + any execution tools supplied by the caller.

    The agent is expected to:
      1. Create a plan using the 'planning' tool
      2. Execute each step with available tools
      3. Terminate when all steps are done

    Usage::

        flow = PlanningFlow(tools=ToolCollection(WebSearchTool(), StrReplaceEditorTool()))
        result = await flow.run("Research and summarize the latest Python releases")
    """

    def __init__(self, tools: ToolCollection | None = None) -> None:
        planning_tool = PlanningTool()
        all_tools: list[BaseTool] = [planning_tool]
        if tools is not None:
            all_tools.extend(list(tools))

        self._agent = ToolCallWeebotAgent(
            tools=ToolCollection(*all_tools),
            system_prompt=PLANNING_SYSTEM_PROMPT,
        )

    async def run(self, prompt: str) -> str:
        """Execute the planning flow for the given task prompt."""
        return await self._agent.run(prompt)
