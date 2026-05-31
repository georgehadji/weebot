"""SSEAdapter — Server-Sent Events notification adapter."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from weebot.application.ports.notification_port import (
    Notification,
    NotificationChannel,
    NotificationConfig,
    NotificationPort,
    NotificationResult,
    NotificationSubscriber,
)


class SSEAdapter(NotificationPort):
    """Notification adapter using Server-Sent Events (SSE).
    
    This adapter broadcasts notifications to connected SSE clients.
    It can be used with FastAPI, Flask-SSE, or any other SSE-capable
    web framework.
    
    Example with FastAPI:
        from fastapi import FastAPI
        from fastapi.responses import StreamingResponse
        
        app = FastAPI()
        sse_adapter = SSEAdapter()
        
        @app.get("/notifications")
        async def notifications():
            return StreamingResponse(
                sse_adapter.subscribe(),
                media_type="text/event-stream"
            )
        
        @app.post("/notify")
        async def send_notification(title: str, message: str):
            await sse_adapter.notify(Notification(title=title, message=message))
    """
    
    def __init__(self, config: Optional[NotificationConfig] = None) -> None:
        """Initialize the SSE adapter.
        
        Args:
            config: Notification configuration. Uses defaults if None.
        """
        self._config = config or NotificationConfig()
        self._queues: list[asyncio.Queue[Notification]] = []
        self._lock = asyncio.Lock()
        self._running = False
    
    @property
    def channel(self) -> NotificationChannel:
        """Return the notification channel."""
        return NotificationChannel.SSE
    
    async def is_available(self) -> bool:
        """Check if SSE adapter is available.
        
        Always returns True as this adapter has no external dependencies.
        """
        return True
    
    async def start(self) -> None:
        """Start the SSE adapter."""
        self._running = True
    
    async def stop(self) -> None:
        """Stop the SSE adapter and cleanup."""
        self._running = False
        async with self._lock:
            self._queues.clear()
    
    async def subscribe(self):
        """Subscribe to notifications as an SSE stream.
        
        Yields:
            Server-sent event formatted strings.
        """
        queue: asyncio.Queue[Notification] = asyncio.Queue()
        
        async with self._lock:
            self._queues.append(queue)
        
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'message': 'Connected to notification stream'})}\n\n"
            
            while self._running:
                try:
                    # Wait for notification with timeout to allow periodic keepalive
                    notification = await asyncio.wait_for(
                        queue.get(),
                        timeout=30.0
                    )
                    
                    # Format as SSE event
                    event_data = {
                        "id": notification.id,
                        "title": notification.title,
                        "message": notification.message,
                        "level": notification.level.name,
                        "channel": notification.channel.name,
                        "timestamp": notification.timestamp.isoformat() if notification.timestamp else None,
                        "metadata": notification.metadata,
                        "actions": notification.actions,
                    }
                    
                    yield f"event: notification\ndata: {json.dumps(event_data)}\n\n"
                
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
        
        finally:
            async with self._lock:
                if queue in self._queues:
                    self._queues.remove(queue)
    
    async def notify(self, notification: Notification) -> NotificationResult:
        """Send a notification to all connected SSE clients.
        
        Args:
            notification: The notification to send.
        
        Returns:
            NotificationResult with send details.
        """
        if not self._running:
            return NotificationResult(
                success=False,
                notification_id=notification.id,
                channel=self.channel,
                error="SSE adapter not started",
            )
        
        # Check level filter
        if not self.should_notify(notification.level, self._config):
            return NotificationResult(
                success=True,
                notification_id=notification.id,
                channel=self.channel,
                metadata={"filtered": True, "reason": "level_below_threshold"},
            )
        
        async with self._lock:
            queues = self._queues.copy()
        
        if not queues:
            return NotificationResult(
                success=True,
                notification_id=notification.id,
                channel=self.channel,
                metadata={"delivered": False, "reason": "no_connected_clients"},
            )
        
        # Send to all queues
        delivered = 0
        failed = 0
        
        for queue in queues:
            try:
                queue.put_nowait(notification)
                delivered += 1
            except asyncio.QueueFull:
                failed += 1
            except Exception:
                failed += 1
        
        return NotificationResult(
            success=delivered > 0,
            notification_id=notification.id,
            channel=self.channel,
            metadata={"delivered": delivered, "failed": failed},
        )
    
    async def check_health(self) -> tuple[bool, str]:
        """Check the health of the SSE adapter.
        
        Returns:
            Tuple of (is_healthy, status_message).
        """
        if not self._running:
            return False, "SSE adapter not started"
        
        async with self._lock:
            client_count = len(self._queues)
        
        return True, f"SSE adapter running with {client_count} connected clients"
    
    async def get_stats(self) -> dict[str, Any]:
        """Get current adapter statistics.
        
        Returns:
            Dictionary with adapter statistics.
        """
        async with self._lock:
            return {
                "running": self._running,
                "connected_clients": len(self._queues),
                "channel": self.channel.name,
            }


class SSEEventSubscriber(NotificationSubscriber):
    """Subscriber that forwards notifications to an SSE adapter.
    
    This subscriber connects to a NotificationBus and forwards
    all notifications to an SSEAdapter for broadcasting.
    
    Example:
        from weebot.application.ports.notification_port import NotificationBus
        
        bus = NotificationBus()
        sse_adapter = SSEAdapter()
        await sse_adapter.start()
        
        subscriber = SSEEventSubscriber(sse_adapter)
        bus.subscribe(subscriber)
    """
    
    def __init__(self, sse_adapter: SSEAdapter) -> None:
        """Initialize the SSE event subscriber.
        
        Args:
            sse_adapter: The SSE adapter to forward notifications to.
        """
        self._sse_adapter = sse_adapter
    
    async def on_notification(self, notification: Notification) -> None:
        """Forward notification to SSE adapter.
        
        Args:
            notification: The notification received.
        """
        await self._sse_adapter.notify(notification)
