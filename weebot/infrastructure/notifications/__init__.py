"""Notification infrastructure adapters.

This module provides notification delivery implementations:
- WindowsToastAdapter: Windows desktop toast notifications
"""

from weebot.application.ports.notification_port import (
    Notification,
    NotificationBus,
    NotificationChannel,
    NotificationConfig,
    NotificationLevel,
    NotificationPort,
    NotificationResult,
    NotificationSubscriber,
)

from weebot.infrastructure.notifications.windows_toast import (
    WindowsToastAdapter,
    WindowsToastEventSubscriber,
    WindowsToastSubscriber,
)

__all__ = [
    "Notification",
    "NotificationBus",
    "NotificationChannel",
    "NotificationConfig",
    "NotificationLevel",
    "NotificationPort",
    "NotificationResult",
    "NotificationSubscriber",
    "WindowsToastAdapter",
    "WindowsToastEventSubscriber",
    "WindowsToastSubscriber",
]
