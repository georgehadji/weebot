"""Notification infrastructure adapters.

This module provides notification delivery implementations:
- WindowsToastAdapter: Windows desktop toast notifications
- SSEAdapter: Server-Sent Events for web clients
- TelegramAdapter: Telegram bot notifications
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

try:
    from weebot.infrastructure.notifications.sse_adapter import SSEAdapter
    SSE_AVAILABLE = True
except ImportError:
    SSE_AVAILABLE = False

try:
    from weebot.infrastructure.notifications.telegram_adapter import TelegramAdapter
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

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
    "SSEAdapter",
    "TelegramAdapter",
    "SSE_AVAILABLE",
    "TELEGRAM_AVAILABLE",
]
