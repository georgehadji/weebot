"""Per-session spend: a running total, a soft limit that degrades, a hard limit that asks.

ORCH-4 / decision D6 of ``tasks/specs/arch_audit_2026_10_remediation_plan.md``. No
per-session USD bound existed on the main flow. A single hard number either never
fires or kills real work (the measured distribution is long-tailed: p99 is 28x the
median), so there are two thresholds, both enforced through mechanisms the repo
already has:

* **soft** (default $0.50, about p99): the cascade stops trying PREMIUM models for
  the rest of the session and a ``SessionBudgetSoftLimit`` event is emitted. No
  interaction.
* **hard** (default $2.50): the flow asks through the ADR-013 approval channel. A
  yes grants exactly one more hard-limit increment; no, or nobody to ask, ends the
  flow as ``BUDGET_EXCEEDED`` with the session persisted and resumable.

The total is held in memory and fed by ``LLMCallCompleted`` events (the cascade's and
the ``BoundedLLMAdapter``'s, so metering is complete); on resume it is seeded once from
the event store. Sub-agent spend is rolled up to the parent session with ``link``.

Either limit set to 0 disables that threshold.
"""

from __future__ import annotations

import logging
from typing import Any

from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval

logger = logging.getLogger(__name__)

BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
BUDGET_TOOL_NAME = "session_budget"


class SessionCostMeter:
    def __init__(
        self,
        soft_usd: float = 0.0,
        hard_usd: float = 0.0,
        event_store: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self.soft_usd = max(0.0, float(soft_usd))
        self.hard_usd = max(0.0, float(hard_usd))
        self._store = event_store
        self._bus = event_bus
        self._totals: dict[str, float] = {}
        self._parent: dict[str, str] = {}
        self._own: dict[str, float] = {}
        self._seeded: set[str] = set()
        self._soft_announced: set[str] = set()

    # ── totals ──────────────────────────────────────────────────────

    def _root(self, session_id: str) -> str:
        seen = {session_id}
        while session_id in self._parent:
            session_id = self._parent[session_id]
            if session_id in seen:  # a cycle would loop forever
                break
            seen.add(session_id)
        return session_id

    def link(self, child_session_id: str, parent_session_id: str) -> None:
        """Count *child*'s spend toward *parent* (a sub-agent rolls up to its parent)."""
        if child_session_id and parent_session_id and child_session_id != parent_session_id:
            self._parent[child_session_id] = parent_session_id

    def add(self, session_id: str, usd: float) -> None:
        if session_id and usd > 0:
            self._own[session_id] = self._own.get(session_id, 0.0) + usd
            root = self._root(session_id)
            self._totals[root] = self._totals.get(root, 0.0) + usd

    def spent(self, session_id: str) -> float:
        """What *session_id* itself spent, apart from the sessions that roll up to it."""
        return self._own.get(session_id, 0.0)

    def total(self, session_id: str) -> float:
        return self._totals.get(self._root(session_id), 0.0) if session_id else 0.0

    def soft_exceeded(self, session_id: str | None, soft_usd: float | None = None) -> bool:
        limit = self.soft_usd if soft_usd is None else soft_usd
        return bool(session_id) and limit > 0 and self.total(session_id or "") >= limit

    # ── feeds ───────────────────────────────────────────────────────

    async def on_domain_event(self, event: Any) -> None:
        """Bus subscriber: fold ``LLMCallCompleted`` into the running total."""
        if getattr(event, "type", "") != "llm_call_completed":
            return
        session_id = getattr(event, "session_id", "") or ""
        self.add(session_id, float(getattr(event, "cost", 0.0) or 0.0))
        await self._announce_soft_limit(session_id)

    async def seed(self, session_id: str) -> None:
        """Seed a resumed session's total from the event store, once."""
        root = self._root(session_id)
        if not root or root in self._seeded or self._store is None:
            return
        self._seeded.add(root)
        try:
            summary = await self._store.get_cost_summary(root)
        except Exception:
            logger.warning("could not seed the cost total for session %s", root, exc_info=True)
            return
        persisted = float((summary or {}).get("total_cost", 0.0) or 0.0)
        if persisted > self._totals.get(root, 0.0):
            self._totals[root] = persisted

    async def _announce_soft_limit(self, session_id: str) -> None:
        root = self._root(session_id)
        if not self.soft_exceeded(root) or root in self._soft_announced:
            return
        self._soft_announced.add(root)
        logger.warning(
            "session %s crossed the soft cost limit ($%.2f >= $%.2f): PREMIUM models are "
            "skipped for the rest of the session",
            root,
            self.total(root),
            self.soft_usd,
        )
        if self._bus is None:
            return
        from weebot.domain.models.event import SessionBudgetSoftLimit

        try:
            await self._bus.publish_domain_event(
                SessionBudgetSoftLimit(
                    session_id=root, total_usd=self.total(root), soft_limit_usd=self.soft_usd
                )
            )
        except Exception:
            logger.warning("SessionBudgetSoftLimit could not be published", exc_info=True)


def budget_prompt(session_id: str, total: float, allowance: float) -> str:
    return (
        f"Session {session_id} has spent ${total:.2f}, which reaches its cost limit of "
        f"${allowance:.2f}. Allow it to continue? (yes/no)"
    )


async def ask_to_continue(session_id: str, total: float, allowance: float) -> tuple[
    ApprovalOutcome, ToolCallApproval
]:
    """Ask through the ADR-013 channel (console, flow pause or deny) whether to go on.

    The fingerprint names the allowance being crossed, so a grant covers exactly this
    increment: after it, the next crossing is a different fingerprint and asks again.
    """
    from weebot.application.services import tool_approval
    from weebot.core.approval import call_fingerprint

    arguments = {"session_id": session_id, "allowance_usd": round(allowance, 4)}
    request = ToolCallApproval(
        session_id=session_id,
        tool_name=BUDGET_TOOL_NAME,
        arguments=arguments,
        fingerprint=call_fingerprint(BUDGET_TOOL_NAME, arguments),
        guard="cost_budget",
        reason=f"session spend ${total:.2f} reached the ${allowance:.2f} limit",
    )
    outcome = await tool_approval.current_approval().resolve(request)
    return outcome, request
