"""TodoWriteTool — self-reported progress checklist (Enhancement 4).

Allows the agent to report structured progress within a step by emitting
TodoEvents that are streamed via SSE to the UI.  Each todo item has a
description, status (pending/in_progress/completed/failed), and progress
percentage.

Emits TodoEvent into the event bus whenever called.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class TodoWriteTool(BaseTool):
    """Track subtask progress within the current step."""

    name: str = "todo_write"
    description: str = (
        "Track progress of subtasks within the current step. "
        "Create a todo item with action='add', update progress with "
        "action='update', or mark complete with action='complete'. "
        "Todo items are streamed to the UI in real-time."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "update", "complete"],
                "description": "Operation: add a new item, update progress, or mark complete.",
            },
            "description": {
                "type": "string",
                "description": "Description of the todo item (required for 'add').",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "failed"],
                "description": "Current status (default: pending for add).",
            },
            "progress": {
                "type": "number",
                "description": "Progress 0.0–1.0 (default: 0.0 for add).",
            },
        },
        "required": ["action"],
    }

    _event_bus: Any = None

    def __init__(self, event_bus=None, **data: Any) -> None:
        super().__init__(**data)
        object.__setattr__(self, "_event_bus", event_bus)

    async def execute(
        self,
        action: str,
        description: str = "",
        status: str = "pending",
        progress: float = 0.0,
        **_: Any,
    ) -> ToolResult:
        if self._event_bus:
            from weebot.domain.models.event import TodoEvent

            await self._event_bus.publish(
                TodoEvent(
                    action=action,
                    description=description,
                    status=status if action == "update" else "in_progress" if action == "add" else "completed",
                    progress=progress,
                )
            )

        if action == "add":
            return ToolResult.success_result(
                output=f"📋 Added: {description}",
                data={"action": action, "description": description, "status": "in_progress"},
            )
        elif action == "complete":
            return ToolResult.success_result(
                output=f"✅ Done: {description}",
                data={"action": action, "description": description, "status": "completed"},
            )
        else:
            return ToolResult.success_result(
                output=f"📝 Updated: {description} ({int(progress * 100)}%)",
                data={"action": action, "description": description, "status": status},
            )
