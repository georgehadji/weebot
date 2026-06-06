"""HyperAgentFlow — state machine wrapper for HyperAgent.

Extends BaseFlow with session management and event publishing.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional, TYPE_CHECKING

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort
from weebot.application.agents.hyper_agent import HyperAgent
from weebot.domain.models.event import AgentEvent, ErrorEvent, MessageEvent
from weebot.domain.models.session import Session, SessionStatus

if TYPE_CHECKING:
    from weebot.application.cqrs.mediator import Mediator

logger = logging.getLogger(__name__)


class HyperAgentFlow(BaseFlow):
    """Multi-agent workflow via HyperAgent orchestrator.

    Wraps HyperAgent.execute() in the BaseFlow protocol by converting
    the SwarmResult into a single MessageEvent yield.
    """

    def __init__(
        self,
        llm: LLMPort,
        session: Session,
        event_bus: EventBusPort,
        swarm_bus: SwarmEventBusPort,
        sub_agent_factory: SubAgentFactoryPort,
        cost_tracker: SubAgentCostTrackerPort,
        model: Optional[str] = None,
        mediator: Optional["Mediator"] = None,
        max_concurrency: int = 4,
    ) -> None:
        self._session = session
        self._event_bus = event_bus
        self._model = model
        self._mediator = mediator
        self._done = False

        self._hyper = HyperAgent(
            llm=llm,
            event_bus=event_bus,
            swarm_bus=swarm_bus,
            sub_agent_factory=sub_agent_factory,
            cost_tracker=cost_tracker,
            model=model,
            max_concurrency=max_concurrency,
        )

    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        self._session = self._session.set_status(SessionStatus.RUNNING)
        logger.info("HyperAgentFlow started: session=%s", self._session.id)

        try:
            swarm_result = await self._hyper.execute(prompt)
            event = MessageEvent(
                role="assistant",
                message=swarm_result.synthesis,
            )
            self._session = self._session.add_event(event)
            if self._event_bus:
                await self._event_bus.publish(event)
            yield event
        except Exception as exc:
            logger.exception("HyperAgentFlow failed: %s", exc)
            yield ErrorEvent(error=str(exc))

        self._session = self._session.set_status(SessionStatus.COMPLETED)
        self._done = True

    def is_done(self) -> bool:
        return self._done
