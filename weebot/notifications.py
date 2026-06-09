"""Compatibility stub for legacy agent_core_v2.py.

The original ``weebot.notifications`` module was removed during the
infrastructure reorganisation.  This stub provides the ``NotificationManager``
class that ``agent_core_v2.WeebotAgent`` expects so that existing tests
continue to pass until ``agent_core_v2.py`` is fully retired.

Target sunset: 2027-03-01 (per agent_core_v2.py header).
"""
from __future__ import annotations

import logging
import warnings

logger = logging.getLogger(__name__)

warnings.warn(
    "weebot.notifications is deprecated. "
    "Use weebot.infrastructure.notifications.* instead.",
    DeprecationWarning,
    stacklevel=2,
)


class NotificationManager:
    """Legacy notification manager stub.

    All methods are no-ops — the actual notification logic now lives in
    ``weebot.infrastructure.notifications`` and the event bus.
    """

    async def notify_project_start(self, project_id: str, description: str) -> None:
        logger.debug("(stub) notify_project_start: %s", project_id)

    async def notify_checkpoint(self, project_id: str, message: str) -> None:
        logger.debug("(stub) notify_checkpoint: %s — %s", project_id, message)

    async def notify_completion(self, project_id: str, message: str) -> None:
        logger.debug("(stub) notify_completion: %s — %s", project_id, message)

    async def notify_error(
        self, project_id: str, message: str, critical: bool = False
    ) -> None:
        logger.debug("(stub) notify_error: %s — %s (critical=%s)", project_id, message, critical)
