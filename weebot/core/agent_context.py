"""Agent context — shared state and event signaling for multi-agent workflows."""

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
    event_type: str  # "agent_completed" | "agent_failed" | "result_ready" | custom
    agent_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class EventBroker:
    """In-memory pub/sub for agent-to-agent signaling.

    Supports both synchronous querying (for immediate results) and
    asynchronous subscriptions (for reactive workflows).
    """

    def __init__(self) -> None:
        # Subscriptions: {event_type: [queue1, queue2, ...]}
        self._subscriptions: Dict[str, List[asyncio.Queue]] = {}
        self._event_history: List[ContextEvent] = []

    async def publish(
        self,
        event_type: str,
        agent_id: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Publish an event to all subscribers."""
        event = ContextEvent(
            event_type=event_type,
            agent_id=agent_id,
            data=data or {}
        )
        self._event_history.append(event)

        # Notify all subscribers for this event type.
        # Snapshot the list first: a concurrent cancellation can call remove()
        # at any await point, causing "list changed size during iteration".
        queues = list(self._subscriptions.get(event_type, []))
        for queue in queues:
            try:
                await asyncio.wait_for(queue.put(event), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.QueueFull):
                _log.warning(
                    "EventBroker: dropped %r event — subscriber queue full/slow",
                    event_type,
                )

    async def subscribe(
        self,
        event_type: str,
        agent_filter: Optional[str] = None
    ) -> AsyncIterator[ContextEvent]:
        """Subscribe to events of a specific type.

        Args:
            event_type: Type of event to subscribe to
            agent_filter: Optional agent_id to filter by

        Yields:
            ContextEvent matching the subscription criteria
        """
        # Bounded queue: if the consumer falls 100 events behind, publish()
        # will time out rather than accumulating events indefinitely.
        queue: asyncio.Queue[ContextEvent] = asyncio.Queue(maxsize=100)

        # Register this queue
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []
        self._subscriptions[event_type].append(queue)

        try:
            while True:
                event = await queue.get()
                if agent_filter is None or event.agent_id == agent_filter:
                    yield event
        finally:
            # Cleanup on exit. Wrap in try/except: a concurrent cancellation
            # racing with another finally can remove the queue first, making
            # this remove() raise ValueError.
            if event_type in self._subscriptions:
                try:
                    self._subscriptions[event_type].remove(queue)
                except ValueError:
                    pass  # Already removed — harmless

    def get_event_history(self, event_type: Optional[str] = None) -> List[ContextEvent]:
        """Get all published events, optionally filtered by type."""
        if event_type is None:
            return list(self._event_history)
        return [e for e in self._event_history if e.event_type == event_type]


@dataclass
class AgentContext:
    """Shared context passed between agents in a multi-agent workflow.

    Supports both synchronous data sharing (dictionary) and asynchronous
    event signaling (pub/sub), enabling flexible agent orchestration patterns.

    Attributes:
        orchestrator_id: Top-level agent that initiated the workflow
        parent_id: Direct parent agent (None for orchestrator)
        agent_id: This agent's unique ID
        nesting_level: Depth in the agent hierarchy (1=orchestrator, 2,3=children)
        shared_data: Dictionary for synchronous data sharing between agents
        event_broker: Pub/sub for async event signaling
        activity_stream: Shared activity log across all agents
        state_manager: Shared state persistence layer
    """

    orchestrator_id: str
    parent_id: Optional[str]
    agent_id: str
    nesting_level: int  # 1 (orchestrator) | 2 | 3

    shared_data: Dict[str, Any] = field(default_factory=dict)
    event_broker: EventBroker = field(default_factory=EventBroker)
    activity_stream: ActivityStream = field(default_factory=ActivityStream)
    state_manager: Optional[StateManager] = None

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
            shared_data=parent_context.shared_data,  # Shared reference
            event_broker=parent_context.event_broker,  # Shared reference
            activity_stream=parent_context.activity_stream,  # Shared reference
            state_manager=parent_context.state_manager
        )

    async def store_result(
        self,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None
    ) -> None:
        """Store a result in shared data, with optional tagging.

        Args:
            key: Key to store under (can be nested like "researcher.findings")
            value: Value to store
            tags: Optional tags for filtering/indexing
        """
        # Support nested keys like "researcher.findings"
        keys = key.split(".")
        current = self.shared_data
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value

        # Log activity
        self.activity_stream.push(
            self.orchestrator_id,
            "context",
            f"{self.agent_id}: stored {key} (tags: {tags or []})"
        )

    async def get_result(self, key: str) -> Optional[Any]:
        """Retrieve a result from shared data.

        Args:
            key: Key to retrieve (supports nested keys)

        Returns:
            Value if found, None otherwise
        """
        keys = key.split(".")
        current = self.shared_data
        for k in keys:
            if not isinstance(current, dict) or k not in current:
                return None
            current = current[k]
        return current

    async def get_sibling_output(self, agent_id: str) -> Optional[Any]:
        """Retrieve output from a sibling agent.

        Searches the shared_data for keys matching the agent's output pattern:
        {agent_id}.output or {agent_id}.result
        """
        # Try common output patterns
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
        """Publish an event for other agents to react to.

        Args:
            event_type: Type of event (e.g., "analysis_complete", "error")
            data: Optional payload data
        """
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
        """Subscribe to events from other agents.

        Args:
            event_type: Type of event to listen for
            agent_filter: Optional agent_id to filter by

        Yields:
            ContextEvent objects matching the filter
        """
        async for event in self.event_broker.subscribe(event_type, agent_filter):
            yield event

    async def checkpoint(
        self,
        message: str,
        requires_approval: bool = False
    ) -> bool:
        """Record a checkpoint in the workflow (optionally requiring approval).

        Args:
            message: Checkpoint message/description
            requires_approval: If True, blocks until user approves (future feature)

        Returns:
            True if approved to continue, False if rejected
        """
        self.activity_stream.push(
            self.orchestrator_id,
            "checkpoint",
            f"{self.agent_id}: {message}"
        )

        # TODO: Integrate with StateManager checkpoint system
        if requires_approval and self.state_manager:
            # Future: call state_manager.checkpoint(...)
            pass

        return True

    def get_activity_log(self, limit: int = 50) -> List[str]:
        """Get recent activity log entries."""
        events = self.activity_stream.recent(n=limit, project_id=self.orchestrator_id)
        return [f"[{e.kind}] {e.message}" for e in events]
