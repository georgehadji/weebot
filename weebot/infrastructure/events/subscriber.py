"""Infrastructure subscriber for domain events."""
import logging
from typing import List

from weebot.domain.models.event import DomainEvent, FactDiscovered, MemoryCompacted, PlanStepCompleted

logger = logging.getLogger("weebot.domain.events")

class InfrastructureEventSubscriber:
    """Listens for domain events and routes them to infrastructure logging/storage."""

    def __init__(self, event_bus=None):
        self._event_bus = event_bus

    async def handle_events(self, events: List[DomainEvent]):
        """Process a list of domain events."""
        for event in events:
            if isinstance(event, FactDiscovered):
                logger.info(f"FACT: [{event.session_id}] Learned {event.key}")
            elif isinstance(event, MemoryCompacted):
                logger.debug(f"MEMORY: [{event.session_id}] Removed {event.events_removed} events")
            elif isinstance(event, PlanStepCompleted):
                logger.info(f"PLAN: [{event.session_id}] Completed step {event.step_id}")

            # Optionally publish to the global event bus
            if self._event_bus:
                await self._event_bus.publish(event)
