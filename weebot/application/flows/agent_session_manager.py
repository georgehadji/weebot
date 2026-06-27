"""AgentSessionManager — session lifecycle for PlanActFlow.

Extracted from PlanActFlow to isolate session lifecycle concerns:
checkpoint, teardown, state transitions, and plan snapshots.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.application.flows.states.base import FlowState

logger = logging.getLogger(__name__)


class AgentSessionManager:
    """Manages session lifecycle for a PlanActFlow instance."""

    def __init__(
        self,
        session: Any,
        plan_history: Any,
        hooks: Optional[Any] = None,
        tracing_port: Optional[Any] = None,
        tools: Optional[Any] = None,
    ) -> None:
        self._session = session
        self._plan_history = plan_history
        self._hooks = hooks
        self._tracing_port = tracing_port
        self._tools = tools
        self._state_entered_at: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────

    @property
    def is_done(self) -> bool:
        from weebot.domain.models.session import SessionStatus
        return self._session.status == SessionStatus.COMPLETED

    async def teardown(self) -> None:
        if self._tools is not None:
            await self._tools.teardown()

    # ── State transitions ────────────────────────────────────────────────

    def set_state(self, state: FlowState, flow: Any) -> None:
        """Change the current flow state and record metrics."""
        import time as _time
        now = _time.monotonic()
        prev_state = getattr(flow, "_state", None)
        prev_name = type(prev_state).__name__ if prev_state else "start"
        prev_duration = (now - self._state_entered_at) if self._state_entered_at else 0.0

        if prev_state is not None:
            try:
                from weebot.application.services.metrics_bridge import get_metrics
                metrics = get_metrics()
                if metrics:
                    metrics.flow_step_duration_seconds.labels(
                        state=prev_name,
                    ).observe(prev_duration)
            except Exception:
                pass

        if self._tracing_port is not None:
            span = self._tracing_port.start_span(f"state.{type(state).__name__}")
            span.set_attribute("flow.session_id", self._session.id)
            span.set_attribute("state.name", type(state).__name__)
            span.end()

        flow._state = state
        self._state_entered_at = now

        logger.info(
            "State transition: %s → %s (%.2fs)",
            prev_name, type(state).__name__, prev_duration,
        )

    # ── Plan snapshots ────────────────────────────────────────────────────

    def snapshot_plan(self, plan: Any) -> None:
        """Push current plan onto the undo stack."""
        if self._plan_history is not None and plan is not None:
            self._plan_history.snapshot(plan)

    # ── Checkpoints ───────────────────────────────────────────────────────

    async def maybe_save_checkpoint(self) -> None:
        if self._hooks is not None:
            try:
                await self._hooks.execute_hooks("checkpoint", {
                    "session_id": self._session.id,
                })
            except Exception:
                pass
