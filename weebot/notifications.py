#!/usr/bin/env python3
"""notifications.py - Multi-Channel Notification System

Λειτουργίες:
------------
1. Αποστολή ειδοποιήσεων μέσω Telegram Bot
2. Αποστολή ειδοποιήσεων μέσω Slack Webhooks
3. Local logging όλων των notifications
4. Διαφορετικά επίπεδα προτεραιότητας

Οδηγίες Χρήσης:
---------------
1. Βασική Αρχικοποίηση:
    notifier = NotificationManager()

2. Project-Specific Notifications:
    await notifier.notify_project_start("proj_001", "Data processing")
    await notifier.notify_checkpoint("proj_001", "Review required")

Περιβαλλοντικές Μεταβλητές:
---------------------------
- TELEGRAM_BOT_TOKEN: Token από @BotFather
- TELEGRAM_CHAT_ID: Chat ID για αποστολή
- SLACK_WEBHOOK_URL: Incoming Webhook URL από Slack Apps
"""
import os
import sys
import asyncio
import aiohttp
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime

from weebot.notifications_categorizer import NotificationCategorizer


class NotificationLevel(Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Notification:
    title: str
    message: str
    level: NotificationLevel
    timestamp: datetime
    project_id: Optional[str] = None
    metadata: Optional[dict] = None
    category: str = "info"


class NotificationManager:
    """Unified notification system supporting multiple channels."""

    def __init__(self) -> None:
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
        self.channels = []

        if self.telegram_token:
            self.channels.append(TelegramChannel(self.telegram_token, self.telegram_chat_id))
        if self.slack_webhook:
            self.channels.append(SlackChannel(self.slack_webhook))

        self.channels.append(LogChannel())  # Always log locally
        if sys.platform == "win32":
            self.channels.append(WindowsToastChannel())
        self._categorizer = NotificationCategorizer()

    async def notify(self, notification: Notification) -> None:
        """Send notification to all configured channels."""
        notification.category = self._categorizer.categorize(
            notification.message, notification.metadata or {}
        )
        tasks = [channel.send(notification) for channel in self.channels]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def notify_project_start(self, project_id: str, description: str) -> None:
        """Notify project initiation."""
        await self.notify(Notification(
            title="🚀 Project Started",
            message=f"Project {project_id}: {description}",
            level=NotificationLevel.INFO,
            timestamp=datetime.now(),
            project_id=project_id
        ))

    async def notify_checkpoint(self, project_id: str, message: str) -> None:
        """Notify checkpoint reached."""
        await self.notify(Notification(
            title="⏸ Checkpoint Reached",
            message=message,
            level=NotificationLevel.WARNING,
            timestamp=datetime.now(),
            project_id=project_id
        ))

    async def notify_completion(self, project_id: str, message: str) -> None:
        """Notify successful completion."""
        await self.notify(Notification(
            title="✅ Project Completed",
            message=message,
            level=NotificationLevel.SUCCESS,
            timestamp=datetime.now(),
            project_id=project_id
        ))

    async def notify_error(self, project_id: str, error: str, critical: bool = False) -> None:
        """Notify error."""
        level = NotificationLevel.CRITICAL if critical else NotificationLevel.ERROR
        await self.notify(Notification(
            title="❌ Error Occurred",
            message=error,
            level=level,
            timestamp=datetime.now(),
            project_id=project_id
        ))


class TelegramChannel:
    """Telegram Bot notification channel."""

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{token}"

    async def send(self, notification: Notification) -> bool:
        """Send message via Telegram."""
        emoji_map = {
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.SUCCESS: "✅",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "❌",
            NotificationLevel.CRITICAL: "🚨"
        }
        
        emoji = emoji_map.get(notification.level, "📌")
        text = f"{emoji} <b>{notification.title}</b>\n\n{notification.message}"
        
        if notification.project_id:
            text += f"\n\nProject: <code>{notification.project_id}</code>"
        
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/sendMessage",
                    json=payload
                ) as response:
                    return response.status == 200
        except Exception as e:
            print(f"Telegram notification failed: {e}")
            return False


class SlackChannel:
    """Slack Webhook notification channel."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send(self, notification: Notification) -> bool:
        """Send message via Slack."""
        color_map = {
            NotificationLevel.INFO: "#36a64f",
            NotificationLevel.SUCCESS: "#28a745",
            NotificationLevel.WARNING: "#ffc107",
            NotificationLevel.ERROR: "#dc3545",
            NotificationLevel.CRITICAL: "#721c24"
        }
        
        payload = {
            "attachments": [{
                "color": color_map.get(notification.level, "#36a64f"),
                "title": notification.title,
                "text": notification.message,
                "footer": f"Project: {notification.project_id}" if notification.project_id else "weebot Agent",
                "ts": int(notification.timestamp.timestamp())
            }]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload
                ) as response:
                    return response.status == 200
        except Exception as e:
            print(f"Slack notification failed: {e}")
            return False


class LogChannel:
    """Local file logging channel."""

    def __init__(self, log_file: str = "notifications.log") -> None:
        self.log_file = log_file

    async def send(self, notification: Notification) -> bool:
        """Log notification to file."""
        import json
        from pathlib import Path
        
        entry = {
            "timestamp": notification.timestamp.isoformat(),
            "level": notification.level.value,
            "title": notification.title,
            "message": notification.message,
            "project_id": notification.project_id
        }
        
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        return True

class WindowsToastChannel:
    """Windows 10/11 native toast notification channel via winotify."""

    # Placeholder icons — all map to StoreLogo until per-category assets are added
    CATEGORY_ICONS: Dict[str, str] = {
        "health":   "ms-appx:///Assets/StoreLogo.png",
        "urgent":   "ms-appx:///Assets/StoreLogo.png",
        "reminder": "ms-appx:///Assets/StoreLogo.png",
        "email":    "ms-appx:///Assets/StoreLogo.png",
        "calendar": "ms-appx:///Assets/StoreLogo.png",
        "build":    "ms-appx:///Assets/StoreLogo.png",
        "error":    "ms-appx:///Assets/StoreLogo.png",
        "info":     "ms-appx:///Assets/StoreLogo.png",
    }

    def __init__(self, app_name: str = "weebot") -> None:
        self.app_name = app_name

    def _icon_for_category(self, category: str) -> str:
        return self.CATEGORY_ICONS.get(category, "ms-appx:///Assets/StoreLogo.png")

    async def send(self, notification: Notification) -> bool:
        """Send a Windows toast notification."""
        try:
            import winotify
        except (ImportError, TypeError):
            return False

        try:
            toast = winotify.Notification(
                app_id=self.app_name,
                title=notification.title,
                msg=notification.message,
                icon=self._icon_for_category(getattr(notification, "category", "info")),
            )
            if getattr(notification, "category", "info") == "urgent":
                toast.set_audio(winotify.audio.Default, loop=True)
            toast.show()
            return True
        except Exception as e:
            print(f"Windows toast failed: {e}")
            return False
