"""Re-export of ``weebot.core.background_tasks``.

The owner of fire-and-forget work moved to ``core`` so that infrastructure, tools
and interfaces (which may not import ``application.services``) can spawn through
it too (CON-1 of ``tasks/specs/arch_audit_2026_10_remediation_plan.md``). Existing
imports of this path keep working; new code can import from either.
"""

from weebot.core.background_tasks import (  # noqa: F401
    DEFAULT_DRAIN_TIMEOUT_S,
    BackgroundTasks,
    get_background_tasks,
)

__all__ = ["DEFAULT_DRAIN_TIMEOUT_S", "BackgroundTasks", "get_background_tasks"]
