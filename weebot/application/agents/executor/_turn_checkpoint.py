"""Checkpoint the workspace before a step's first file-changing tool call (H5).

``ToolExecutor.execute_tool`` calls this for every tool call. The port keeps one checkpoint
per (session, step) and none when nothing changed, so asking again is cheap; ``reads_only``
(the classifier the untrusted-content gate already uses) keeps read-only calls from
paying for a git index scan at all.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weebot.application.agents.executor._tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


async def checkpoint_before_change(
    executor: ToolExecutor, name: str, args: dict[str, Any]
) -> None:
    """Take the checkpoint. Never raises: a checkpoint must not block the call it guards."""
    port = executor._workspace_checkpoints
    if port is None:
        return
    from weebot.application.services.tool_guards import reads_only
    from weebot.config.settings import WORKSPACE_ROOT

    try:
        if reads_only(name, args):
            return
        await port.snapshot(
            session_id=executor._current_session_id or "unknown",
            turn_id=executor._current_step_id or "unknown",
            root=WORKSPACE_ROOT,
            reason=name,
        )
    except Exception:
        logger.warning("workspace checkpoint before %s failed", name, exc_info=True)
