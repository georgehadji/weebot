"""TelegramAdapter — Telegram bot notification adapter."""
from __future__ import annotations

from typing import Any, Optional

from weebot.application.ports.notification_port import (
    Notification,
    NotificationChannel,
    NotificationConfig,
    NotificationLevel,
    NotificationPort,
    NotificationResult,
)


class TelegramAdapter(NotificationPort):
    """Notification adapter using Telegram Bot API.
    
    Sends notifications via Telegram messages using a bot token.
    Supports text messages with optional formatting (Markdown/HTML).
    
    Requires: TELEGRAM_BOT_TOKEN environment variable or token parameter
    
    Example:
        notifier = TelegramAdapter(
            bot_token="your_bot_token",
            chat_id="your_chat_id"
        )
        if await notifier.is_available():
            result = await notifier.notify(
                Notification(
                    title="Weebot Alert",
                    message="Task failed!",
                    level=NotificationLevel.ERROR,
                )
            )
    """
    
    # Telegram API base URL
    API_BASE = "https://api.telegram.org/bot"
    
    # Level to emoji mapping
    LEVEL_EMOJI = {
        NotificationLevel.DEBUG: "🔍",
        NotificationLevel.INFO: "ℹ️",
        NotificationLevel.SUCCESS: "✅",
        NotificationLevel.WARNING: "⚠️",
        NotificationLevel.ERROR: "❌",
        NotificationLevel.CRITICAL: "🚨",
    }
    
    # Cleanup is handled via async context manager, explicit close(), or
    # __del__ fallback. The aiohttp.ClientSession is created lazily and
    # closed automatically when the adapter is exited or garbage-collected.
    #
    # Usage with automatic cleanup:
    #   async with TelegramAdapter(bot_token="...", chat_id="...") as n:
    #       await n.notify(...)

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        config: Optional[NotificationConfig] = None,
    ) -> None:
        """Initialize the Telegram adapter.
        
        Args:
            bot_token: Telegram bot token. Reads from TELEGRAM_BOT_TOKEN env if not provided.
            chat_id: Default chat ID to send to. Reads from TELEGRAM_CHAT_ID env if not provided.
            config: Notification configuration.
        """
        self._config = config or NotificationConfig()
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._http_client: Optional[Any] = None
    
    @property
    def channel(self) -> NotificationChannel:
        """Return the notification channel."""
        return NotificationChannel.PUSH
    
    def _get_token(self) -> Optional[str]:
        """Get the bot token from parameter or environment."""
        if self._bot_token:
            return self._bot_token
        
        import os
        return os.getenv("TELEGRAM_BOT_TOKEN")
    
    def _get_chat_id(self) -> Optional[str]:
        """Get the chat ID from parameter or environment."""
        if self._chat_id:
            return self._chat_id
        
        import os
        return os.getenv("TELEGRAM_CHAT_ID")
    
    async def is_available(self) -> bool:
        """Check if Telegram notifications are available.
        
        Returns:
            True if bot token and chat ID are configured.
        """
        try:
            import aiohttp
        except ImportError:
            return False
        
        return self._get_token() is not None and self._get_chat_id() is not None
    
    def _get_http_client(self):
        """Get or create HTTP client."""
        if self._http_client is None:
            import aiohttp
            self._http_client = aiohttp.ClientSession()
        return self._http_client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client and not self._http_client.closed:
            await self._http_client.close()
            self._http_client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    def __del__(self):
        if self._http_client is not None and not self._http_client.closed:
            import asyncio as _asyncio
            try:
                loop = _asyncio.get_running_loop()
            except RuntimeError:
                # No running loop — safe to call asyncio.run()
                _asyncio.run(self._http_client.close())
            else:
                # Running loop exists — schedule close on it
                loop.create_task(self._http_client.close())
    
    def _format_message(self, notification: Notification) -> str:
        """Format notification as Telegram message.
        
        Args:
            notification: The notification to format.
        
        Returns:
            Formatted message text.
        """
        emoji = self.LEVEL_EMOJI.get(notification.level, "📢")
        
        lines = [
            f"{emoji} *{self._escape_markdown(notification.title)}*",
            "",
            self._escape_markdown(notification.message),
        ]
        
        # Add metadata if present
        if notification.metadata:
            lines.append("")
            lines.append("_Details:_")
            for key, value in notification.metadata.items():
                lines.append(f"• {self._escape_markdown(key)}: `{self._escape_markdown(str(value))}`")
        
        return "\n".join(lines)
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special characters for Telegram MarkdownV2.
        
        Args:
            text: Text to escape.
        
        Returns:
            Escaped text.
        """
        # Characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
        chars_to_escape = r"_\*\[\]\(\)~`>#\+\-=|\{\}\.!"
        import re
        return re.sub(f"([{chars_to_escape}])", r"\\\1", text)
    
    async def notify(self, notification: Notification) -> NotificationResult:
        """Send a notification via Telegram.
        
        Args:
            notification: The notification to send.
        
        Returns:
            NotificationResult with send details.
        """
        token = self._get_token()
        chat_id = self._get_chat_id()
        
        if not token:
            return NotificationResult(
                success=False,
                notification_id=notification.id,
                channel=self.channel,
                error="Telegram bot token not configured",
            )
        
        if not chat_id:
            return NotificationResult(
                success=False,
                notification_id=notification.id,
                channel=self.channel,
                error="Telegram chat ID not configured",
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
            import aiohttp
        except ImportError:
            return NotificationResult(
                success=False,
                notification_id=notification.id,
                channel=self.channel,
                error="aiohttp not installed",
            )
        
        message_text = self._format_message(notification)
        url = f"{self.API_BASE}{token}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": message_text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        
        try:
            session = self._get_http_client()
            async with session.post(url, json=payload) as response:
                result = await response.json()
                
                if response.status == 200 and result.get("ok"):
                    message_id = result.get("result", {}).get("message_id")
                    return NotificationResult(
                        success=True,
                        notification_id=str(message_id) if message_id else notification.id,
                        channel=self.channel,
                        metadata={
                            "telegram_message_id": message_id,
                            "chat_id": chat_id,
                        },
                    )
                else:
                    error = result.get("description", "Unknown error")
                    return NotificationResult(
                        success=False,
                        notification_id=notification.id,
                        channel=self.channel,
                        error=f"Telegram API error: {error}",
                    )
        
        except Exception as e:
            return NotificationResult(
                success=False,
                notification_id=notification.id,
                channel=self.channel,
                error=str(e),
            )
    
    async def check_health(self) -> tuple[bool, str]:
        """Check the health of the Telegram adapter.
        
        Returns:
            Tuple of (is_healthy, status_message).
        """
        try:
            import aiohttp
        except ImportError:
            return False, "aiohttp not installed"
        
        token = self._get_token()
        chat_id = self._get_chat_id()
        
        if not token:
            return False, "Telegram bot token not configured"
        
        if not chat_id:
            return False, "Telegram chat ID not configured"
        
        # Try to get bot info to verify token works
        try:
            url = f"{self.API_BASE}{token}/getMe"
            session = self._get_http_client()
            async with session.get(url) as response:
                result = await response.json()
                if response.status == 200 and result.get("ok"):
                    bot_name = result.get("result", {}).get("username", "Unknown")
                    return True, f"Telegram bot @{bot_name} ready"
                else:
                    error = result.get("description", "Unknown error")
                    return False, f"Telegram API error: {error}"
        except Exception as e:
            return False, f"Connection error: {e}"
