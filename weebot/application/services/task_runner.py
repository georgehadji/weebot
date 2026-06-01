"""Background task runner for agent sessions."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.memory_archivist import MemoryArchivist
from weebot.domain.models.event import AgentEvent
from weebot.domain.models.session import Session, SessionStatus

# Prometheus metrics — lazy import
_metrics_mod = None
def _get_tr_metrics():
    global _metrics_mod
    if _metrics_mod is None:
        from weebot.infrastructure.observability import metrics as m
        _metrics_mod = m
    return _metrics_mod
from weebot.application.models.tool_collection import ToolCollection

logger = logging.getLogger(__name__)

FlowFactory = Callable[[Session], BaseFlow]


@dataclass(order=True)
class PrioritizedSession:
    priority: int
    session: Session = field(compare=False)
    flow_factory: FlowFactory = field(compare=False)


class TaskRunner:
    """Runs agent flows as background asyncio tasks with session persistence."""

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        event_bus: Optional[EventBusPort] = None,
        archivist: Optional[MemoryArchivist] = None,
        max_pending: int = 100,
        max_session_retries: int = 2,
    ):
        self._state_repo = state_repo
        self._event_bus = event_bus
        self._archivist = archivist
        self._max_session_retries = max_session_retries
        self._tasks: Dict[str, asyncio.Task] = {}
        self._priority_queue: asyncio.PriorityQueue[PrioritizedSession] = asyncio.PriorityQueue(maxsize=max_pending)
        self._worker_task: Optional[asyncio.Task] = None
        self._retry_counts: Dict[str, int] = {}  # session_id -> attempts remaining
        self._flow_factories: Dict[str, FlowFactory] = {}  # session_id -> factory for retries

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker(), name="weebot-taskrunner-worker")

    async def _worker(self) -> None:
        """Background worker that consumes the priority queue."""
        while True:
            try:
                prioritized = await self._priority_queue.get()
            except asyncio.CancelledError:
                break
            await self._start_direct(prioritized.session, prioritized.flow_factory)
            self._priority_queue.task_done()

    async def _start_direct(
        self,
        session: Session,
        flow_factory: FlowFactory,
    ) -> Session:
        """Internal direct task creation (bypasses queue)."""
        session = session.set_status(SessionStatus.RUNNING)
        await self._state_repo.save_session(session)
        session_id = session.id

        # Record the factory so _run_flow can retry on failure
        self._flow_factories[session_id] = flow_factory
        if session_id not in self._retry_counts:
            self._retry_counts[session_id] = self._max_session_retries

        task = asyncio.create_task(
            self._run_flow(session_id, flow_factory(session)),
            name=f"weebot-session-{session_id}",
        )
        self._tasks[session_id] = task

        def _cleanup(t: asyncio.Task) -> None:
            self._tasks.pop(session_id, None)
            self._flow_factories.pop(session_id, None)
            self._retry_counts.pop(session_id, None)
            if t.exception():
                logger.error("Session %s failed: %s", session_id, t.exception())

        task.add_done_callback(_cleanup)
        return session

    async def start_session(
        self,
        session: Session,
        flow_factory: FlowFactory,
    ) -> Session:
        """Start a session immediately as a background task."""
        return await self._start_direct(session, flow_factory)

    async def enqueue_session(
        self,
        session: Session,
        flow_factory: FlowFactory,
        priority: int = 5,
    ) -> Session:
        """Enqueue a session with priority for later execution."""
        self._ensure_worker()
        await self._priority_queue.put(PrioritizedSession(priority, session, flow_factory))
        return session

    async def _run_flow(self, session_id: str, flow: BaseFlow) -> None:
        """Internal runner that persists events and handles completion."""
        session = await self._state_repo.load_session(session_id)
        if session is None:
            logger.error("Session %s not found for background run", session_id)
            return

        # Session metrics
        try:
            _get_tr_metrics().session_active.inc()
            _get_tr_metrics().session_total.inc()
        except Exception:
            pass

        try:
            async for event in flow.run(session.context.get("last_prompt", "")):
                session = session.add_event(event)
                if self._archivist is not None:
                    session = await self._archivist.archive_old_events(session)
                await self._state_repo.save_session(session)
                # Only publish from the runner when the flow has no event_bus of its
                # own.  When the flow carries an event_bus (the DI container always
                # provides one), flow._emit() already published the event; publishing
                # here too would deliver every event twice to all subscribers (double
                # WebSocket messages, double Prometheus counts, double notifications).
                flow_has_bus = getattr(flow, "_event_bus", None) is not None
                if self._event_bus and not flow_has_bus:
                    await self._event_bus.publish(event)
                # (comment block ends — the line above is the only publish call)
                # Prometheus counts, double notification triggers).
        except Exception as exc:
            logger.exception("Flow failed for session %s", session_id)
            # Session-level retry: requeue with exponential backoff
            remaining = self._retry_counts.get(session_id, 0)
            if remaining > 0:
                self._retry_counts[session_id] = remaining - 1
                backoff = 5.0 * (2 ** (self._max_session_retries - remaining))
                logger.info(
                    "Retrying session %s in %.0fs (%d retries remaining)",
                    session_id, backoff, remaining - 1,
                )
                await asyncio.sleep(backoff)
                factory = self._flow_factories.get(session_id)
                if factory:
                    reloaded = await self._state_repo.load_session(session_id)
                    if reloaded:
                        await self._start_direct(reloaded, factory)
                        return
            session = session.set_status(SessionStatus.FAILED)
            await self._state_repo.save_session(session)
        else:
            # Sync flow-mutated state (facts, compaction) back into
            # the local session before final save. The flow modifies
            # flow._session independently of this runner's copy.
            flow_session = getattr(flow, "_session", None)
            if flow_session is not None:
                session = session.model_copy(update={
                    "context": flow_session.context,
                })
            if flow.is_done():
                session = session.set_status(SessionStatus.COMPLETED)
            else:
                session = session.set_status(SessionStatus.WAITING)
            await self._state_repo.save_session(session)
        finally:
            try:
                _get_tr_metrics().session_active.dec()
            except Exception:
                pass

    async def resume_session(
        self,
        session_id: str,
        answer: str,
        flow_factory: FlowFactory,
    ) -> Session:
        """Resume a waiting session by injecting a user answer."""
        session = await self._state_repo.load_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")

        if session.status != SessionStatus.WAITING:
            raise ValueError(
                f"Session {session_id} is not waiting for input (current status: {session.status.value})"
            )

        session = session.add_user_message(answer)
        session = session.set_status(SessionStatus.RUNNING)
        await self._state_repo.save_session(session)
        await self.start_session(session, flow_factory)

        return session

    async def cancel_session(self, session_id: str) -> bool:
        """Cancel a running session."""
        task = self._tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await self._state_repo.update_session_status(session_id, SessionStatus.FAILED)
            return True
        return False

    async def shutdown(self) -> None:
        """Cancel worker and wait for queue drain."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def list_active_sessions(self) -> List[str]:
        """List IDs of currently running sessions."""
        return [sid for sid, t in self._tasks.items() if not t.done()]

    async def list_all_sessions(
        self,
        status_filter: Optional[SessionStatus] = None,
    ) -> List[Session]:
        """List all persisted sessions with optional status filtering."""
        sessions = await self._state_repo.list_sessions()
        if status_filter is not None:
            sessions = [s for s in sessions if s.status == status_filter]
        return sessions

    @staticmethod
    def create_plan_act_factory(
        llm: LLMPort,
        tools: ToolCollection,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
    ) -> FlowFactory:
        """Factory helper to create PlanActFlow instances."""
        from weebot.application.flows.plan_act_flow import PlanActFlow

        def _factory(session: Session) -> BaseFlow:
            return PlanActFlow(
                llm=llm,
                tools=tools,
                session=session,
                event_bus=event_bus,
                model=model,
                state_repo=self._state_repo,
            )
        return _factory
