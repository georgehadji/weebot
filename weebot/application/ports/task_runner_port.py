"""TaskRunnerPort — narrow structural interface for interfaces-layer callers.

``TaskRunner`` (application/services/task_runner.py) is correctly placed in
the application layer, but its own imports reach into infrastructure
(metrics) and ``weebot.tools`` (via ``PlanActFlow``'s tool assembler).
Anything in ``interfaces/`` that imports the concrete ``TaskRunner`` class
therefore pulls in that whole transitive surface and breaks the
"interfaces must not depend on infrastructure/tools directly" import-linter
contract — regardless of how carefully the importing file itself behaves.

This Protocol exposes exactly the operations ``interfaces/web/routers/sessions.py``
and ``dispatch_session_input.py`` call, so the interfaces layer can depend on
a narrow structural type instead of the wide concrete class. Same shape and
justification as the existing ``EventBusPort``/``EventPublisherPort`` split.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from collections.abc import Callable

if TYPE_CHECKING:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.steering_port import SteeringPort
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import Session

FlowFactory = Callable[["Session"], object]


@runtime_checkable
class TaskRunnerPort(Protocol):
    """The subset of ``TaskRunner`` the interfaces layer is allowed to call."""

    async def cancel_session(self, session_id: str) -> bool:
        """Cancel a running session. Returns False if none was active."""
        ...

    async def start_session(self, session: Session, flow_factory: FlowFactory) -> Session:
        """Start a session immediately as a background task."""
        ...

    def create_plan_act_factory(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        event_bus: EventBusPort | None = None,
        model: str | None = None,
        ponytail_mode: str | None = None,
        steering: SteeringPort | None = None,
    ) -> FlowFactory:
        """Build a ``PlanActFlow`` factory bound to the given collaborators."""
        ...
