"""DispatchAgentsTool — spawn multiple independent sub-agents in parallel.

Implements the foreman pattern: a lead agent breaks a task into independent
sub-tasks and dispatches specialist sub-agents concurrently via asyncio.gather.
Each sub-agent runs a full PlanActFlow in its own ephemeral Session.

This mirrors the BenchmarkRunner.run_batch() concurrency pattern but is
invocable as a tool from within an ExecutorAgent loop.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from pydantic import ConfigDict

from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class DispatchAgentsTool(BaseTool):
    """Spawn N independent sub-agents to run tasks in parallel.

    Each task runs as a full PlanActFlow in its own Session. Results are
    collected and returned as a structured list in ToolResult.data.

    Injected dependencies (not Pydantic fields):
        _flow_factory: Callable[[Session], BaseFlow] — builds a flow per session.
        _state_repo: StateRepositoryPort — persists ephemeral sessions.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "dispatch_parallel_tasks"
    description: str = (
        "Spawn multiple independent sub-agents to run tasks concurrently. "
        "Each task gets its own PlanActFlow. Use for parallelisable work such as "
        "building independent UI sections, running parallel research, or executing "
        "independent build steps. Returns a list of per-task summaries."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "List of independent tasks to execute in parallel.",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Unique identifier for this task (used in results).",
                        },
                        "description": {
                            "type": "string",
                            "description": "Full prompt passed to the sub-agent's PlanActFlow.",
                        },
                        "context": {
                            "type": "string",
                            "description": (
                                "Optional extra context prepended to description — "
                                "typically a spec file path or inline spec."
                            ),
                        },
                    },
                    "required": ["task_id", "description"],
                },
                "minItems": 1,
            },
            "max_concurrency": {
                "type": "integer",
                "description": "Maximum number of tasks to run at the same time (default: 4).",
                "default": 4,
            },
        },
        "required": ["tasks"],
    }

    # Private injected dependencies — excluded from Pydantic schema
    _flow_factory: Optional[Callable] = None
    _state_repo: Optional[Any] = None

    def __init__(self, flow_factory: Optional[Callable] = None, state_repo: Optional[Any] = None, **data):
        super().__init__(**data)
        # Store via object.__setattr__ to bypass Pydantic's frozen model
        object.__setattr__(self, "_flow_factory", flow_factory)
        object.__setattr__(self, "_state_repo", state_repo)

    async def execute(
        self,
        tasks: List[Dict[str, Any]],
        max_concurrency: int = 4,
        **_,
    ) -> ToolResult:
        if not self._flow_factory:
            return ToolResult.error_result(
                "DispatchAgentsTool has no flow_factory — wire it via di.configure_web_clone()"
            )

        if not tasks:
            return ToolResult.error_result("tasks list must not be empty")

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_one(task_spec: Dict[str, Any]) -> Dict[str, Any]:
            task_id = task_spec.get("task_id", str(uuid.uuid4())[:8])
            description = task_spec.get("description", "")
            context = task_spec.get("context", "")
            prompt = f"{context}\n\n{description}".strip() if context else description

            async with semaphore:
                session = self._make_session(task_id)
                try:
                    flow = self._flow_factory(session)
                    summary_lines: List[str] = []
                    async for event in flow.run(prompt):
                        # Collect the final MessageEvent text as the task summary
                        event_type = getattr(event, "type", None) or getattr(event, "event_type", None)
                        if event_type in ("message", "MESSAGE"):
                            content = getattr(event, "content", None) or getattr(event, "message", "")
                            summary_lines.append(str(content))
                    summary = summary_lines[-1] if summary_lines else "(no output)"
                    return {"task_id": task_id, "status": "completed", "summary": summary}
                except Exception as exc:
                    logger.warning("Sub-agent failed for task_id=%s: %s", task_id, exc)
                    return {"task_id": task_id, "status": "failed", "error": str(exc)}

        results = list(await asyncio.gather(*[_run_one(t) for t in tasks]))

        completed = [r for r in results if r.get("status") == "completed"]
        failed = [r for r in results if r.get("status") == "failed"]
        summary = (
            f"Dispatched {len(tasks)} sub-agents: "
            f"{len(completed)} completed, {len(failed)} failed."
        )
        if failed:
            summary += " Failed: " + ", ".join(r["task_id"] for r in failed)

        return ToolResult.success_result(
            output=summary,
            data={"results": results, "completed": len(completed), "failed": len(failed)},
        )

    def _make_session(self, task_id: str):
        """Create an ephemeral Session for a sub-agent run."""
        from weebot.domain.models.session import Session

        session_id = f"dispatch-{task_id}-{uuid.uuid4().hex[:8]}"
        session = Session(
            id=session_id,
            user_id="dispatch_agents",
            agent_id=f"sub-agent-{task_id}",
            context={"dispatch_task_id": task_id},
        )

        # Persist if state_repo is available (non-critical, best-effort)
        if self._state_repo:
            try:
                # Synchronous save if available
                save = getattr(self._state_repo, "save_sync", None)
                if save:
                    save(session)
            except Exception:
                pass

        return session
