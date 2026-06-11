"""Windows toast notification subscriber for the event bus."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.domain.models.event import AgentEvent, DoneEvent, ErrorEvent, StepEvent, WaitForUserEvent


class WindowsToastSubscriber:
    """Subscribes to agent events and shows Windows toast notifications for key milestones."""

    def __init__(self, app_name: str = "weebot", channel: Optional[object] = None) -> None:
        self._app_name = app_name
        self._channel = channel
        if self._channel is None:
            try:
                from weebot.infrastructure.notifications.notifications import WindowsToastChannel
                self._channel = WindowsToastChannel(app_name=app_name)
            except Exception:
                pass

    async def on_event(self, event: AgentEvent) -> None:
        """Handle an agent event and show a toast if relevant."""
        if self._channel is None:
            return

        from weebot.application.ports.notification_port import Notification, NotificationLevel

        notification: Optional[Notification] = None

        if isinstance(event, ErrorEvent):
            notification = Notification(
                title="Weebot Error",
                message=event.error,
                level=NotificationLevel.ERROR,
                timestamp=datetime.now(),
                category="error",
            )
        elif isinstance(event, WaitForUserEvent):
            notification = Notification(
                title="Weebot Needs Input",
                message=event.question,
                level=NotificationLevel.WARNING,
                timestamp=datetime.now(),
                category="urgent",
            )
        elif isinstance(event, DoneEvent):
            notification = Notification(
                title="Weebot Done",
                message="Task completed successfully.",
                level=NotificationLevel.SUCCESS,
                timestamp=datetime.now(),
                category="info",
            )
        elif isinstance(event, StepEvent):
            if event.status.value == "failed":
                notification = Notification(
                    title="Step Failed",
                    message=f"{event.description}",
                    level=NotificationLevel.ERROR,
                    timestamp=datetime.now(),
                    category="error",
                )

        if notification is not None:
            await self._channel.send(notification)

    def subscribe_to(self, bus: EventBusPort) -> None:
        """Register this subscriber on the given event bus."""
        bus.subscribe(self.on_event)

    def unsubscribe_from(self, bus: EventBusPort) -> None:
        """Unregister this subscriber from the given event bus."""
        bus.unsubscribe(self.on_event)
