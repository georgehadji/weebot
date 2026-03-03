"""Agent context v2 - with concurrency safety fixes.

DEV IMPLEMENTATION - Issue #1: Race Condition Fix
- Added asyncio.Lock for shared_data mutations
- Added concurrent-safe data access methods
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

_log = logging.getLogger(__name__)

from weebot.activity_stream import ActivityStream
from weebot.state_manager import StateManager


@dataclass
class ContextEvent:
    """Event published by agents for async coordination."""
    event_type: str
    agent_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class EventBroker:
    """In-memory pub/sub for agent-to-agent signaling WITH RETRY BACKOFF (Issue #2 Fix)."""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0) -> None:
        self._subscriptions: Dict[str, List[asyncio.Queue]] = {}
        self._event_history: List[ContextEvent] = []
        self._max_retries = max_retries
        self._base_delay = base_delay

    async def publish(
        self,
        event_type: str,
        agent_id: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Publish an event to all subscribers WITH RETRY BACKOFF."""
        event = ContextEvent(
            event_type=event_type,
            agent_id=agent_id,
            data=data or {}
        )
        self._event_history.append(event)

        queues = list(self._subscriptions.get(event_type, []))
        for queue in queues:
            # Retry with exponential backoff
            for attempt in range(self._max_retries):
                try:
                    await asyncio.wait_for(queue.put(event), timeout=5.0)
                    break  # Success, move to next queue
                except (asyncio.TimeoutError, asyncio.QueueFull):
                    delay = self._base_delay * (2 ** attempt)
                    _log.warning(
                        "EventBroker: retry %d/%d for %r event after %.1fs",
                        attempt + 1, self._max_retries, event_type, delay
                    )
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(delay)
                    else:
                        _log.error(
                            "EventBroker: FAILED to deliver %r event after %d retries",
                            event_type, self._max_retries
                        )

    async def subscribe(
        self,
        event_type: str,
        agent_filter: Optional[str] = None
    ) -> AsyncIterator[ContextEvent]:
        """Subscribe to events of a specific type."""
        queue: asyncio.Queue[ContextEvent] = asyncio.Queue(maxsize=100)

        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []
        self._subscriptions[event_type].append(queue)

        try:
            while True:
                event = await queue.get()
                if agent_filter is None or event.agent_id == agent_filter:
                    yield event
        finally:
            if event_type in self._subscriptions:
                try:
                    self._subscriptions[event_type].remove(queue)
                except ValueError:
                    pass

    def get_event_history(self, event_type: Optional[str] = None) -> List[ContextEvent]:
        """Get all published events, optionally filtered by type."""
        if event_type is None:
            return list(self._event_history)
        return [e for e in self._event_history if e.event_type == event_type]


@dataclass
class AgentContext:
    """Shared context WITH CONCURRENCY SAFETY (Issue #1 Fix)."""

    orchestrator_id: str
    parent_id: Optional[str]
    agent_id: str
    nesting_level: int

    shared_data: Dict[str, Any] = field(default_factory=dict)
    event_broker: EventBroker = field(default_factory=EventBroker)
    activity_stream: ActivityStream = field(default_factory=ActivityStream)
    state_manager: Optional[StateManager] = None
    
    # CONCURRENCY FIX: Lock for shared_data mutations
    # NOTE: This lock is SHARED between parent and all children to protect
    # the shared_data dictionary. This means slow operations block all agents.
    # For high-contention scenarios, consider sharding by key prefix.
    _data_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self) -> None:
        """Validate nesting level."""
        if not (1 <= self.nesting_level <= 3):
            raise ValueError(f"nesting_level must be 1-3, got {self.nesting_level}")

        if self.nesting_level == 1 and self.parent_id is not None:
            raise ValueError("Orchestrator (level 1) cannot have a parent")

        if self.nesting_level > 1 and self.parent_id is None:
            raise ValueError(f"Agent at level {self.nesting_level} must have a parent")

    @classmethod
    def create_orchestrator(
        cls,
        activity_stream: Optional[ActivityStream] = None,
        state_manager: Optional[StateManager] = None
    ) -> AgentContext:
        """Create a root orchestrator context."""
        agent_id = f"orchestrator_{uuid.uuid4().hex[:8]}"
        return cls(
            orchestrator_id=agent_id,
            parent_id=None,
            agent_id=agent_id,
            nesting_level=1,
            activity_stream=activity_stream or ActivityStream(),
            state_manager=state_manager
        )

    @classmethod
    def create_child(
        cls,
        parent_context: AgentContext,
        parent_agent_id: str,
        role: str
    ) -> AgentContext:
        """Create a child context from a parent context."""
        if parent_context.nesting_level >= 3:
            raise RuntimeError(
                f"Cannot spawn child: parent is at max nesting level {parent_context.nesting_level}"
            )

        agent_id = f"{role}_{uuid.uuid4().hex[:8]}"
        return cls(
            orchestrator_id=parent_context.orchestrator_id,
            parent_id=parent_agent_id,
            agent_id=agent_id,
            nesting_level=parent_context.nesting_level + 1,
            shared_data=parent_context.shared_data,
            event_broker=parent_context.event_broker,
            activity_stream=parent_context.activity_stream,
            state_manager=parent_context.state_manager,
            # CRITICAL: Share the same lock to protect shared_data
            _data_lock=parent_context._data_lock
        )

    async def store_result(
        self,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None
    ) -> None:
        """Store a result WITH LOCK PROTECTION."""
        # Capture key info for logging BEFORE releasing lock
        key_for_log = key
        
        async with self._data_lock:
            # Support nested keys like "researcher.findings"
            keys = key.split(".")
            current = self.shared_data
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]

            current[keys[-1]] = value

        # Log activity (outside lock to reduce contention)
        # NOTE: Don't include value in log to avoid large/side-effect issues
        self.activity_stream.push(
            self.orchestrator_id,
            "context",
            f"{self.agent_id}: stored {key_for_log} (tags: {tags or []})"
        )

    async def get_result(self, key: str) -> Optional[Any]:
        """Retrieve a result WITH LOCK PROTECTION."""
        async with self._data_lock:
            keys = key.split(".")
            current = self.shared_data
            for k in keys:
                if not isinstance(current, dict) or k not in current:
                    return None
                current = current[k]
            return current

    async def get_sibling_output(self, agent_id: str) -> Optional[Any]:
        """Retrieve output from a sibling agent."""
        for pattern in [f"{agent_id}.output", f"{agent_id}.result"]:
            value = await self.get_result(pattern)
            if value is not None:
                return value
        return None

    async def publish_event(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Publish an event for other agents to react to."""
        await self.event_broker.publish(event_type, self.agent_id, data)
        self.activity_stream.push(
            self.orchestrator_id,
            "event",
            f"{self.agent_id} published {event_type}"
        )

    async def subscribe_to_events(
        self,
        event_type: str,
        agent_filter: Optional[str] = None
    ) -> AsyncIterator[ContextEvent]:
        """Subscribe to events from other agents."""
        async for event in self.event_broker.subscribe(event_type, agent_filter):
            yield event

    async def checkpoint(
        self,
        message: str,
        requires_approval: bool = False
    ) -> bool:
        """Record a checkpoint in the workflow."""
        self.activity_stream.push(
            self.orchestrator_id,
            "checkpoint",
            f"{self.agent_id}: {message}"
        )

        if requires_approval and self.state_manager:
            pass  # Future: integrate with StateManager

        return True

    def get_activity_log(self, limit: int = 50) -> List[str]:
        """Get recent activity log entries."""
        events = self.activity_stream.recent(n=limit, project_id=self.orchestrator_id)
        return [f"[{e.kind}] {e.message}" for e in events]
