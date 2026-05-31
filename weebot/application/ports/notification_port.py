"""NotificationPort — abstraction for notification systems.

This port defines the interface for sending notifications to users
via various channels (desktop toast, SSE, Telegram, etc.).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional


class NotificationLevel(Enum):
    """Severity levels for notifications."""
    DEBUG = auto()
    INFO = auto()
    SUCCESS = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


class NotificationChannel(Enum):
    """Available notification channels."""
    DESKTOP = auto()
    EMAIL = auto()
    SMS = auto()
    PUSH = auto()
    WEBHOOK = auto()
    SSE = auto()


@dataclass(frozen=True)
class Notification:
    """A notification to be sent.
    
    Attributes:
        title: Notification title.
        message: Notification message body.
        level: Severity level.
        channel: Target channel.
        id: Unique notification identifier.
        timestamp: When the notification was created.
        metadata: Additional data for the notification.
        actions: Optional action buttons/links.
        expires_at: Optional expiration time.
    """
    title: str
    message: str
    level: NotificationLevel = NotificationLevel.INFO
    channel: NotificationChannel = NotificationChannel.DESKTOP
    id: str = ""
    timestamp: datetime = None
    metadata: dict[str, Any] | None = None
    actions: list[dict[str, str]] | None = None
    expires_at: datetime | None = None
    
    def __post_init__(self):
        if self.timestamp is None:
            object.__setattr__(
                self, 
                'timestamp', 
                datetime.now()
            )


@dataclass(frozen=True)
class NotificationResult:
    """Result of a notification send attempt.
    
    Attributes:
        success: Whether notification was sent successfully.
        notification_id: ID of the notification.
        channel: Channel used.
        error: Error message if send failed.
        delivered_at: When notification was delivered.
        metadata: Additional result data.
    """
    success: bool
    notification_id: str
    channel: NotificationChannel
    error: str | None = None
    delivered_at: datetime = None
    metadata: dict[str, Any] | None = None
    
    def __post_init__(self):
        if self.delivered_at is None:
            object.__setattr__(
                self,
                'delivered_at',
                datetime.now()
            )


@dataclass
class NotificationConfig:
    """Configuration for notification adapters.
    
    Attributes:
        min_level: Minimum level to notify (filters lower levels).
        rate_limit_per_minute: Maximum notifications per minute.
        default_ttl_seconds: Default time-to-live for notifications.
        channels: Enabled channels.
    """
    min_level: NotificationLevel = NotificationLevel.DEBUG
    rate_limit_per_minute: int = 60
    default_ttl_seconds: int = 3600
    channels: list[NotificationChannel] = None
    
    def __post_init__(self):
        if self.channels is None:
            self.channels = [NotificationChannel.DESKTOP]


class NotificationPort(ABC):
    """Abstract base class for notification systems.
    
    Implementations provide notification delivery via various channels
    such as desktop toast, server-sent events, webhooks, etc.
    
    Example:
        notifier = WindowsToastAdapter()
        if await notifier.is_available():
            result = await notifier.notify(
                Notification(
                    title="Task Complete",
                    message="Your task has finished successfully",
                    level=NotificationLevel.SUCCESS,
                )
            )
            if result.success:
                print("Notification sent!")
    """
    
    @property
    @abstractmethod
    def channel(self) -> NotificationChannel:
        """Return the notification channel this adapter uses."""
        ...
    
    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this notification channel is available.
        
        Returns:
            True if notifications can be sent via this channel.
        """
        ...
    
    @abstractmethod
    async def notify(self, notification: Notification) -> NotificationResult:
        """Send a notification.
        
        Args:
            notification: The notification to send.
        
        Returns:
            NotificationResult with send details.
        """
        ...
    
    async def notify_many(
        self,
        notifications: list[Notification],
    ) -> list[NotificationResult]:
        """Send multiple notifications.
        
        Default implementation sends sequentially. Subclasses may
        override for batch/parallel sending.
        
        Args:
            notifications: List of notifications to send.
        
        Returns:
            List of NotificationResult for each send attempt.
        """
        results = []
        for n in notifications:
            result = await self.notify(n)
            results.append(result)
        return results
    
    @abstractmethod
    async def check_health(self) -> tuple[bool, str]:
        """Check the health of the notification channel.
        
        Returns:
            Tuple of (is_healthy, status_message).
        """
        ...
    
    def should_notify(self, level: NotificationLevel, config: NotificationConfig) -> bool:
        """Check if a notification level should be sent based on config.
        
        Args:
            level: The notification level to check.
            config: Notification configuration.
        
        Returns:
            True if the level meets the minimum threshold.
        """
        level_priority = {
            NotificationLevel.DEBUG: 0,
            NotificationLevel.INFO: 1,
            NotificationLevel.SUCCESS: 2,
            NotificationLevel.WARNING: 3,
            NotificationLevel.ERROR: 4,
            NotificationLevel.CRITICAL: 5,
        }
        
        return level_priority.get(level, 0) >= level_priority.get(config.min_level, 0)


class NotificationSubscriber(ABC):
    """Abstract base class for notification subscribers.
    
    Implementations receive notifications from a NotificationBus
    and handle them appropriately (e.g., display, log, forward).
    """
    
    @abstractmethod
    async def on_notification(self, notification: Notification) -> None:
        """Handle a received notification.
        
        Args:
            notification: The notification received.
        """
        ...


class NotificationBus:
    """In-memory bus for distributing notifications to subscribers.
    
    This is a simple pub/sub mechanism for notifications within
    the application. For cross-process notifications, use a
    NotificationPort implementation.
    
    Example:
        bus = NotificationBus()
        
        # Subscribe
        subscriber = MySubscriber()
        bus.subscribe(subscriber)
        
        # Publish
        await bus.publish(Notification(title="Hello", message="World"))
    """
    
    def __init__(self):
        """Initialize the notification bus."""
        self._subscribers: list[NotificationSubscriber] = []
    
    def subscribe(self, subscriber: NotificationSubscriber) -> None:
        """Subscribe to notifications.
        
        Args:
            subscriber: Subscriber to add.
        """
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)
    
    def unsubscribe(self, subscriber: NotificationSubscriber) -> None:
        """Unsubscribe from notifications.
        
        Args:
            subscriber: Subscriber to remove.
        """
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)
    
    async def publish(self, notification: Notification) -> None:
        """Publish a notification to all subscribers.
        
        Args:
            notification: Notification to publish.
        """
        import asyncio
        
        if not self._subscribers:
            return
        
        # Send to all subscribers concurrently
        await asyncio.gather(
            *[s.on_notification(notification) for s in self._subscribers],
            return_exceptions=True,
        )
