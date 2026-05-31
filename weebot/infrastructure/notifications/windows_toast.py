"""WindowsToastAdapter — Windows desktop toast notifications."""
from __future__ import annotations

import sys
from typing import Optional

from weebot.application.ports.notification_port import (
    Notification,
    NotificationChannel,
    NotificationConfig,
    NotificationLevel,
    NotificationPort,
    NotificationResult,
)


class WindowsToastAdapter(NotificationPort):
    """Notification adapter for Windows desktop toast notifications.
    
    Uses the win10toast or windows-toasts library to display
    native Windows toast notifications.
    
    Requires: pip install win10toast (classic) or windows-toasts (modern)
    
    Example:
        notifier = WindowsToastAdapter()
        if await notifier.is_available():
            result = await notifier.notify(
                Notification(
                    title="Weebot",
                    message="Task completed successfully!",
                    level=NotificationLevel.SUCCESS,
                )
            )
    """
    
    # Level to icon mapping
    LEVEL_ICONS = {
        NotificationLevel.DEBUG: "info",
        NotificationLevel.INFO: "info",
        NotificationLevel.SUCCESS: "info",
        NotificationLevel.WARNING: "warning",
        NotificationLevel.ERROR: "error",
        NotificationLevel.CRITICAL: "error",
    }
    
    def __init__(self, config: Optional[NotificationConfig] = None) -> None:
        """Initialize the Windows toast adapter.
        
        Args:
            config: Notification configuration. Uses defaults if None.
        """
        self._config = config or NotificationConfig()
        self._toaster: Optional[object] = None
        self._lib_type: Optional[str] = None
    
    @property
    def channel(self) -> NotificationChannel:
        """Return the notification channel."""
        return NotificationChannel.DESKTOP
    
    async def is_available(self) -> bool:
        """Check if Windows toast notifications are available.
        
        Returns:
            True on Windows with win10toast or windows-toasts installed.
        """
        if sys.platform != "win32":
            return False
        
        try:
            import win10toast
            self._lib_type = "win10toast"
            return True
        except ImportError:
            pass
        
        try:
            import windows_toasts
            self._lib_type = "windows_toasts"
            return True
        except ImportError:
            pass
        
        return False
    
    def _get_toaster(self):
        """Get or create the toast notifier instance."""
        if self._toaster is not None:
            return self._toaster
        
        if self._lib_type == "win10toast":
            from win10toast import ToastNotifier
            self._toaster = ToastNotifier()
        elif self._lib_type == "windows_toasts":
            from windows_toasts import Toast, WindowsToaster
            self._toaster = WindowsToaster("Weebot")
        
        return self._toaster
    
    async def notify(self, notification: Notification) -> NotificationResult:
        """Send a Windows toast notification.
        
        Args:
            notification: The notification to send.
        
        Returns:
            NotificationResult with send details.
        """
        if not await self.is_available():
            return NotificationResult(
                success=False,
                notification_id=notification.id,
                channel=self.channel,
                error="Windows toast notifications not available",
            )
        
        # Check level filter
        if not self.should_notify(notification.level, self._config):
            return NotificationResult(
                success=True,
                notification_id=notification.id,
                channel=self.channel,
                metadata={"filtered": True, "reason": "level_below_threshold"},
            )
        
        try:
            toaster = self._get_toaster()
            icon = self.LEVEL_ICONS.get(notification.level, "info")
            
            if self._lib_type == "win10toast":
                # Use win10toast
                toaster.show_toast(
                    title=notification.title,
                    msg=notification.message,
                    icon_path=None,
                    duration=10,  # seconds
                    threaded=True,
                )
            elif self._lib_type == "windows_toasts":
                # Use windows_toasts (modern)
                from windows_toasts import Toast, ToastDisplayImage, ToastImagePosition
                
                toast = Toast()
                toast.text_fields = [notification.title, notification.message]
                
                # Add actions if provided
                if notification.actions:
                    for action in notification.actions:
                        # windows-toasts supports actions differently
                        pass
                
                toaster.show_toast(toast)
            
            return NotificationResult(
                success=True,
                notification_id=notification.id,
                channel=self.channel,
                metadata={"library": self._lib_type, "icon": icon},
            )
        
        except Exception as e:
            return NotificationResult(
                success=False,
                notification_id=notification.id,
                channel=self.channel,
                error=str(e),
            )
    
    async def check_health(self) -> tuple[bool, str]:
        """Check the health of the Windows toast notification system.
        
        Returns:
            Tuple of (is_healthy, status_message).
        """
        if sys.platform != "win32":
            return False, "Not running on Windows"
        
        available = await self.is_available()
        if not available:
            return False, "Windows toast library not installed (win10toast or windows-toasts)"
        
        return True, f"Windows toast ready ({self._lib_type})"


class WindowsToastSubscriber:
    """Helper class to subscribe to notifications and show toast popups.
    
    This subscriber connects to a NotificationBus and displays
    Windows toast notifications for each notification received.
    
    Example:
        from weebot.application.ports.notification_port import NotificationBus
        
        bus = NotificationBus()
        subscriber = WindowsToastSubscriber()
        bus.subscribe(subscriber)
        
        # Now any notification published to the bus will show a toast
    """
    
    def __init__(self, config: Optional[NotificationConfig] = None) -> None:
        """Initialize the toast subscriber.
        
        Args:
            config: Notification configuration.
        """
        self._adapter = WindowsToastAdapter(config)
        self._available: Optional[bool] = None
    
    async def on_notification(self, notification: Notification) -> None:
        """Handle a received notification by showing a toast.
        
        Args:
            notification: The notification received.
        """
        if self._available is None:
            self._available = await self._adapter.is_available()
        
        if self._available:
            await self._adapter.notify(notification)


class WindowsToastEventSubscriber:
    """Event subscriber that shows Windows toast notifications for agent events.
    
    This subscriber connects to the AsyncEventBus and displays toast notifications
    for important agent events like task completion, errors, or human input requests.
    
    Example:
        from weebot.infrastructure.event_bus import get_event_bus
        from weebot.infrastructure.notifications import WindowsToastEventSubscriber
        
        subscriber = WindowsToastEventSubscriber()
        subscriber.subscribe_to(get_event_bus())
        
        # Now important events will show toast notifications
    """
    
    def __init__(self, config: Optional[NotificationConfig] = None) -> None:
        """Initialize the toast event subscriber.
        
        Args:
            config: Notification configuration.
        """
        self._adapter = WindowsToastAdapter(config)
        self._available: Optional[bool] = None
        self._event_bus = None
    
    def subscribe_to(self, event_bus) -> None:
        """Subscribe to an AsyncEventBus.
        
        Args:
            event_bus: The AsyncEventBus to subscribe to.
        """
        from weebot.application.ports.event_bus_port import EventHandler
        
        self._event_bus = event_bus
        event_bus.subscribe(self._on_event)
    
    def unsubscribe(self) -> None:
        """Unsubscribe from the event bus."""
        if self._event_bus:
            self._event_bus.unsubscribe(self._on_event)
            self._event_bus = None
    
    async def _on_event(self, event) -> None:
        """Handle agent events and show toast notifications for important ones.
        
        Args:
            event: The AgentEvent received.
        """
        from weebot.domain.models.event import (
            DoneEvent,
            ErrorEvent,
            WaitForUserEvent,
            StepEvent,
            StepStatus,
        )
        
        if self._available is None:
            self._available = await self._adapter.is_available()
        
        if not self._available:
            return
        
        # Convert important events to notifications
        notification = None
        
        if isinstance(event, DoneEvent):
            notification = Notification(
                title="Weebot - Task Complete",
                message="Your task has been completed successfully.",
                level=NotificationLevel.SUCCESS,
                channel=NotificationChannel.DESKTOP,
            )
        elif isinstance(event, ErrorEvent):
            error_msg = getattr(event, 'error', 'Unknown error')
            # Truncate long error messages
            if len(error_msg) > 100:
                error_msg = error_msg[:97] + "..."
            notification = Notification(
                title="Weebot - Error",
                message=f"An error occurred: {error_msg}",
                level=NotificationLevel.ERROR,
                channel=NotificationChannel.DESKTOP,
            )
        elif isinstance(event, WaitForUserEvent):
            question = getattr(event, 'question', 'Input needed')
            # Truncate long questions
            if len(question) > 100:
                question = question[:97] + "..."
            notification = Notification(
                title="Weebot - Input Needed",
                message=f"The agent needs your input: {question}",
                level=NotificationLevel.INFO,
                channel=NotificationChannel.DESKTOP,
            )
        elif isinstance(event, StepEvent):
            # Notify on step completion for long-running tasks
            if getattr(event, 'status', None) == StepStatus.COMPLETED:
                step_desc = getattr(event, 'description', 'Step completed')
                if step_desc and len(step_desc) > 100:
                    step_desc = step_desc[:97] + "..."
                notification = Notification(
                    title="Weebot - Step Complete",
                    message=step_desc or "A step has been completed.",
                    level=NotificationLevel.INFO,
                    channel=NotificationChannel.DESKTOP,
                )
        
        if notification:
            await self._adapter.notify(notification)
