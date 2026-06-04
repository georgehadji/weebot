"""WorkflowOrchestratorTool — DAG-based multi-agent workflow execution.

Unlike DispatchAgentsTool (pure parallelism), this tool respects dependency
ordering — tasks run as their dependencies complete, with up to 4 concurrent
agents.  Each task spawns a full PlanActFlow sub-agent.

Exposes the WorkflowOrchestrator as an agent-callable tool.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from pydantic import ConfigDict

from weebot.core.workflow_orchestrator import (
    WorkflowOrchestrator,
    WorkflowResult,
    TaskResult,
    TaskStatus,
)
from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_TASK_DESC_MAX_LEN = 2048


class WorkflowOrchestratorTool(BaseTool):
    """Execute a DAG of sub-tasks with dependency-respecting parallelism.

    Each task in the DAG runs as a full PlanActFlow sub-agent. Tasks whose
    dependencies are met run concurrently (up to max_parallel).  Use this
    when task execution order matters — pure parallelism where all tasks
    are independent should use dispatch_parallel_tasks instead.

    Injected dependencies (not Pydantic fields):
        _flow_factory: Callable[[Session], BaseFlow] — builds a flow per session.
        _state_repo: StateRepositoryPort — persists ephemeral sessions.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "workflow_orchestrator"
    description: str = (
        "Execute a DAG of sub-tasks with dependency-aware parallelism. "
        "Each task is a dict with 'task_id', 'description' (prompt), "
        "and 'deps' (list of task_ids it depends on).  Tasks run concurrently "
        "up to max_parallel as their dependencies complete.  Ideal for "
        "multi-step workflows like 'fetch data → analyze → generate report' "
        "where some steps depend on others."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": (
                    "List of tasks forming a dependency graph. Each task has: "
                    "task_id (unique id), description (the prompt for the sub-agent), "
                    "deps (list of task_ids this task depends on). Tasks with "
                    "empty deps start immediately."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Unique identifier for this task.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Full prompt passed to the sub-agent's PlanActFlow.",
                        },
                        "deps": {
                            "type": "array",
                            "description": "List of task_ids this task depends on (empty list = no deps).",
                            "items": {"type": "string"},
                            "default": [],
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Per-task timeout in seconds (default: 300).",
                        },
                    },
                    "required": ["task_id", "description"],
                },
                "minItems": 1,
            },
            "max_parallel": {
                "type": "integer",
                "description": "Maximum number of tasks to run concurrently (1-10, default: 4).",
                "default": 4,
            },
        },
        "required": ["tasks"],
    }

    # Private injected dependencies — excluded from Pydantic schema
    _flow_factory: Optional[Callable] = None
    _state_repo: Optional[Any] = None

    def __init__(
        self,
        flow_factory: Optional[Callable] = None,
        state_repo: Optional[Any] = None,
        **data,
    ):
        super().__init__(**data)
        object.__setattr__(self, "_flow_factory", flow_factory)
        object.__setattr__(self, "_state_repo", state_repo)

    async def execute(
        self,
        tasks: List[Dict[str, Any]],
        max_parallel: int = 4,
        **_,
    ) -> ToolResult:
        if not self._flow_factory:
            return ToolResult.error_result(
                "WorkflowOrchestratorTool has no flow_factory — "
                "wire it via di.configure_web_clone() or configure_defaults()"
            )
        if not tasks:
            return ToolResult.error_result("tasks list must not be empty")

        # ── Build task_graph in the format WorkflowOrchestrator expects ──
        task_graph: Dict[str, Dict[str, Any]] = {}
        for t in tasks:
            tid = t.get("task_id")
            if not tid:
                return ToolResult.error_result("Every task must have a 'task_id'")
            description = t.get("description", "")
            if not description:
                return ToolResult.error_result(f"Task '{tid}' missing 'description'")
            deps = t.get("deps", [])
            if not isinstance(deps, list):
                return ToolResult.error_result(f"Task '{tid}': 'deps' must be a list")
            task_graph[tid] = {
                "deps": list(deps),
                "description": description[: _TASK_DESC_MAX_LEN],
                "timeout": t.get("timeout", 300),
            }

        # ── Build a real task handler that spawns sub-agent flows ──
        async def _agent_task_handler(
            task_id: str,
            task_config: Dict[str, Any],
            context: Any,  # AgentContext from WorkflowOrchestrator
        ) -> Dict[str, Any]:
            description = task_config.get("description", "")
            semaphore = asyncio.Semaphore(max_parallel)

            async with semaphore:
                session = self._make_session(task_id)
                flow = self._flow_factory(session)
                summary_lines: List[str] = []
                prompt = description
                try:
                    async for event in flow.run(prompt):
                        event_type = (
                            getattr(event, "type", None)
                            or getattr(event, "event_type", None)
                        )
                        if event_type in ("message", "MESSAGE"):
                            content = (
                                getattr(event, "content", None)
                                or getattr(event, "message", "")
                            )
                            summary_lines.append(str(content))
                    summary = summary_lines[-1] if summary_lines else "(no output)"
                    return {
                        "task_id": task_id,
                        "status": "completed",
                        "summary": summary[:2000],
                    }
                except Exception as exc:
                    logger.warning(
                        "DAG sub-agent failed for task_id=%s: %s", task_id, exc
                    )
                    return {
                        "task_id": task_id,
                        "status": "failed",
                        "error": str(exc)[:500],
                    }

        orchestrator = WorkflowOrchestrator(
            max_parallel_agents=min(max(1, max_parallel), 10),
            timeout_per_task=300,
            task_handler=_agent_task_handler,
        )

        try:
            result: WorkflowResult = await orchestrator.execute(task_graph)
        except Exception as exc:
            logger.exception("WorkflowOrchestrator execution failed")
            return ToolResult.error_result(f"Orchestration error: {exc}")

        # ── Build structured output ──
        total_tasks = result.metadata.get("total_tasks", len(tasks))
        completed = [
            {
                "task_id": tid,
                "summary": result.task_results[tid].output.get("summary", "")
                if isinstance(result.task_results[tid].output, dict)
                else str(result.task_results[tid].output),
            }
            for tid in result.completed_tasks
        ]
        failed = [
            {
                "task_id": tid,
                "error": result.task_results[tid].error or "unknown",
            }
            for tid in result.failed_tasks
        ]

        summary = (
            f"DAG workflow finished: "
            f"{len(result.completed_tasks)}/{total_tasks} completed, "
            f"{len(result.failed_tasks)} failed "
            f"({result.execution_time_ms:.0f}ms)."
        )
        if failed:
            summary += " Failed: " + ", ".join(r["task_id"] for r in failed)

        return ToolResult.success_result(
            output=summary,
            data={
                "success": result.success,
                "completed": completed,
                "failed": failed,
                "total_tasks": total_tasks,
                "execution_time_ms": result.execution_time_ms,
            },
        )

    def _make_session(self, task_id: str):
        """Create an ephemeral Session for a sub-agent run."""
        from weebot.domain.models.session import Session

        session_id = f"dag-{task_id}-{uuid.uuid4().hex[:8]}"
        session = Session(
            id=session_id,
            user_id="workflow_orchestrator",
            agent_id=f"dag-agent-{task_id}",
            context={"dag_task_id": task_id},
        )

        if self._state_repo:
            try:
                save = getattr(self._state_repo, "save_sync", None)
                if save:
                    save(session)
            except Exception:
                pass

        return session
