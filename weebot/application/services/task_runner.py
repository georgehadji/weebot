"""Background task runner for agent sessions."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from collections.abc import Callable

from weebot.application.abstractions import BaseFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.task_queue_port import TaskQueuePort
from weebot.domain.models.session import Session, SessionStatus

if TYPE_CHECKING:
    from weebot.application.ports.steering_port import SteeringPort

from weebot.application.services.metrics_bridge import get_metrics as _get_tr_metrics
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
        event_bus: EventBusPort | None = None,
        max_pending: int = 100,
        max_session_retries: int = 3,
        task_queue: TaskQueuePort | None = None,
    ):
        self._state_repo = state_repo
        self._event_bus = event_bus
        self._max_session_retries = max_session_retries
        self._tasks: dict[str, asyncio.Task] = {}
        self._task_queue: TaskQueuePort | None = task_queue
        # Fallback to asyncio.PriorityQueue when no external queue is provided
        self._priority_queue: asyncio.PriorityQueue[PrioritizedSession] = asyncio.PriorityQueue(maxsize=max_pending) if task_queue is None else None  # type: ignore[assignment]
        self._worker_task: asyncio.Task | None = None
        self._retry_counts: dict[str, int] = {}  # session_id -> attempts remaining
        self._flow_factories: dict[str, FlowFactory] = {}  # session_id -> factory for retries
        self._failed_sessions: dict[str, int] = (
            {}
        )  # session_id -> retry count exhausted (dead-letter queue)

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker(), name="weebot-taskrunner-worker")

    async def _worker(self) -> None:
        """Background worker that consumes the task queue."""
        if self._task_queue is not None:
            # External queue (Redis) — use TaskQueuePort interface
            while True:
                try:
                    item = await self._task_queue.dequeue()
                except asyncio.CancelledError:
                    break
                if item is None:
                    break  # Queue was closed
                await self._start_direct(item.session, item.flow_factory)
                await self._task_queue.ack(item)
        else:
            # Legacy in-memory queue
            while True:
                try:
                    prioritized = await self._priority_queue.get()
                except asyncio.CancelledError:
                    break
                await self._start_direct(prioritized.session, prioritized.flow_factory)
                self._priority_queue.task_done()

    async def _publish_presence(self, session: Session) -> None:
        """Emit a SessionPresenceEvent on the global channel for the session rail.

        No-op when no event bus is configured (CLI/tests). See
        ``SessionPresenceEvent``'s docstring for why this doesn't go
        through ``session_id`` — it must reach every connected rail, not
        just the one session's own socket.
        """
        if self._event_bus is None:
            return
        from weebot.domain.models.event import SessionPresenceEvent

        try:
            await self._event_bus.publish(
                SessionPresenceEvent(
                    about_session_id=session.id,
                    status=session.status.value,
                    title=session.title or "",
                )
            )
        except Exception:
            logger.debug("Failed to publish session presence for %s", session.id, exc_info=True)

    async def _start_direct(self, session: Session, flow_factory: FlowFactory) -> Session:
        """Internal direct task creation (bypasses queue)."""
        session = session.set_status(SessionStatus.RUNNING)
        await self._state_repo.save_session(session)
        await self._publish_presence(session)
        session_id = session.id

        # Record the factory so _run_flow can retry on failure
        self._flow_factories[session_id] = flow_factory
        if session_id not in self._retry_counts:
            self._retry_counts[session_id] = self._max_session_retries

        task = asyncio.create_task(
            self._run_flow(session_id, flow_factory(session)), name=f"weebot-session-{session_id}"
        )
        self._tasks[session_id] = task

        def _cleanup(t: asyncio.Task) -> None:
            # Only pop if this task is the one currently tracked.
            # When a retry creates a new task via _start_direct, the old
            # task's cleanup must not remove the new task from _tasks.
            if self._tasks.get(session_id) is t:
                self._tasks.pop(session_id, None)
            # Only clean up retry state when no more retries are expected.
            # If _retry_counts > 0, a retry task is in-flight and owns the
            # count; popping here would kill the retry task's counter
            # before it can read it, leaving it with 0 retries remaining.
            remaining = self._retry_counts.get(session_id, 0)
            if remaining <= 0:
                self._flow_factories.pop(session_id, None)
                self._retry_counts.pop(session_id, None)
            # `Task.exception()` RAISES CancelledError when the task was
            # cancelled, and cancelling a session is an ordinary operation --
            # `flow cancel <id>` is a CLI command. Unguarded, every cancellation
            # pushed a CancelledError into the loop's exception handler from
            # inside this callback. It corrupted nothing, because the cleanup
            # above had already run, but it filled the log with a spurious error
            # on a normal path -- which buries a real cleanup failure in a stream
            # of identical noise.
            if t.cancelled():
                logger.debug("Session %s was cancelled", session_id)
                return
            exc = t.exception()
            if exc is not None:
                logger.error("Session %s failed: %s", session_id, exc)

        task.add_done_callback(_cleanup)
        return session

    async def start_session(self, session: Session, flow_factory: FlowFactory) -> Session:
        """Start a session immediately as a background task."""
        return await self._start_direct(session, flow_factory)

    async def enqueue_session(
        self, session: Session, flow_factory: FlowFactory, priority: int = 5
    ) -> Session:
        """Enqueue a session with priority for later execution."""
        self._ensure_worker()
        if self._task_queue is not None:
            await self._task_queue.enqueue(session, flow_factory, priority=priority)
        else:
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
            logger.debug("Failed to increment session metrics", exc_info=True)

        try:
            async for event in flow.run(session.context.get("last_prompt", "")):
                session = session.add_event(event)
                await self._state_repo.save_session(session)
                # Only publish from the runner when the flow has no event_bus of its
                # own.  When the flow carries an event_bus (the DI container always
                # provides one), flow._emit() already published the event; publishing
                # here too would deliver every event twice to all subscribers (double
                # WebSocket messages, double Prometheus counts, double notifications).
                flow_has_bus = getattr(flow, "_event_bus", None) is not None
                if self._event_bus and not flow_has_bus:
                    await self._event_bus.publish(event)
        except Exception:
            logger.exception("Flow failed for session %s", session_id)
            # Session-level retry: requeue with exponential backoff
            remaining = self._retry_counts.get(session_id, 0)
            if remaining > 0:
                self._retry_counts[session_id] = remaining - 1
                backoff = 5.0 * (2 ** (self._max_session_retries - remaining))
                logger.info(
                    "Retrying session %s in %.0fs (%d retries remaining)",
                    session_id,
                    backoff,
                    remaining - 1,
                )
                await asyncio.sleep(backoff)
                factory = self._flow_factories.get(session_id)
                if factory:
                    reloaded = await self._state_repo.load_session(session_id)
                    if reloaded:
                        await self._start_direct(reloaded, factory)
                        return
            try:
                session = session.set_status(SessionStatus.FAILED)
                await self._state_repo.save_session(session)
                await self._publish_presence(session)
            except Exception as persist_exc:
                logger.error(
                    "Double failure: state repo write failed after flow crash "
                    "for session %s — session may be orphaned in RUNNING state. "
                    "Error: %s",
                    session_id,
                    persist_exc,
                )
            finally:
                # Dead-letter queue: track sessions that exhausted all retries
                self._failed_sessions[session_id] = self._max_session_retries
        else:
            # Sync flow-mutated state (facts, compaction) back into
            # the local session before final save. The flow modifies
            # flow._session independently of this runner's copy.
            flow_session = getattr(flow, "_session", None)
            if flow_session is not None:
                session = session.model_copy(update={"context": flow_session.context})
            if flow.is_done():
                session = session.set_status(SessionStatus.COMPLETED)
            else:
                session = session.set_status(SessionStatus.WAITING)
            await self._state_repo.save_session(session)
            await self._publish_presence(session)
        finally:
            try:
                await flow.teardown()
            except Exception:
                logger.debug("Flow teardown error for session %s", session_id, exc_info=True)
            try:
                _get_tr_metrics().session_active.dec()
            except Exception:
                logger.debug("Failed to decrement session active metric", exc_info=True)

    async def resume_session(
        self, session_id: str, answer: str, flow_factory: FlowFactory
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

    async def rerun_failed_session(self, session_id: str) -> bool:
        """Re-enter a permanently-failed session at the last saved state.

        Restores the session from the state repo and re-submits it through
        the original flow factory.  Resets the retry counter so the newly
        spawned attempt gets a full retry budget.

        Returns:
            True if the session was found and re-started, False otherwise.
        """
        session = await self._state_repo.load_session(session_id)
        if session is None:
            logger.warning("rerun_failed_session: session %s not found", session_id)
            return False
        if session.status != SessionStatus.FAILED:
            logger.warning(
                "rerun_failed_session: session %s status is %s, not FAILED",
                session_id,
                session.status.value,
            )
            return False

        factory = self._flow_factories.pop(session_id, None)
        if factory is None:
            # Try the default PlanActFlow factory builder fallback
            logger.warning(
                "rerun_failed_session: no flow factory cached for %s "
                "— attempting resume with default factory",
                session_id,
            )
            return False

        # Clear dead-letter and retry state so the new attempt gets a clean
        # retry budget.
        self._failed_sessions.pop(session_id, None)
        self._retry_counts.pop(session_id, None)

        await self._start_direct(session, factory)
        logger.info("Rerun initiated for failed session %s", session_id)
        return True

    async def list_failed_sessions(self) -> dict[str, int]:
        """Return sessions in the dead-letter queue with retry counts.

        Returns:
            Dict mapping session_id → number of retries attempted.
        """
        return dict(self._failed_sessions)

    async def shutdown(self) -> None:
        """Cancel worker and wait for queue drain."""
        if self._task_queue is not None:
            await self._task_queue.close()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def list_active_sessions(self) -> list[str]:
        """List IDs of currently running sessions."""
        return [sid for sid, t in self._tasks.items() if not t.done()]

    async def list_all_sessions(self, status_filter: SessionStatus | None = None) -> list[Session]:
        """List all persisted sessions with optional status filtering."""
        sessions = await self._state_repo.list_sessions()
        if status_filter is not None:
            sessions = [s for s in sessions if s.status == status_filter]
        return sessions

    def create_plan_act_factory(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        event_bus: EventBusPort | None = None,
        model: str | None = None,
        ponytail_mode: str | None = None,
        steering: SteeringPort | None = None,
    ) -> FlowFactory:
        """Factory helper to create PlanActFlow instances.

        *steering*, when provided, lets a running flow observe non-blocking
        mid-execution feedback sent via ``SteeringPort.send()`` — see
        ``PlanActFlow``'s per-step ``steering.poll()`` call. Without it,
        the web ``/sessions/{id}/steer`` endpoint has nothing to deliver to.
        """
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.services.ponytail_skill_prompt import build_ponytail_skill_prompt

        state_repo = self._state_repo
        skill_prompt = build_ponytail_skill_prompt(existing=None, mode=ponytail_mode)

        def _factory(session: Session) -> BaseFlow:
            from weebot.application.services.session_scoped_event_bus import SessionScopedEventBus

            scoped_bus = SessionScopedEventBus(event_bus, session.id) if event_bus else None
            return PlanActFlow(
                llm=llm,
                tools=tools,
                session=session,
                event_bus=scoped_bus,
                model=model,
                skill_prompt=skill_prompt,
                state_repo=state_repo,
                steering=steering,
            )

        return _factory
