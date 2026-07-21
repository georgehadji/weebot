"""StateTransition model and declarative state graph for PlanActFlow.

Replaces hard-coded priority numbers in FlowRouter with a data-driven
transition table.  Adding a new state requires only a new entry in the
transition list — no edits to the router loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from weebot.domain.models.session import Session


@dataclass
class StateTransition:
    """A single declarative transition rule.

    Attributes:
        name: Human-readable transition name (for logging).
        condition: Callable that returns True when this transition applies.
        state_factory: Callable that returns the target state name.
        priority: Lower number = checked first.
    """
    name: str
    condition: Callable[[Session, str, Optional[dict]], bool]
    state_factory: Callable[[Session, str, Optional[dict]], tuple[str, Session]]
    priority: int = 10


class StateGraph:
    """Manages a sorted transition table for state resolution.

    Usage::

        graph = StateGraph()
        graph.add_transition(
            StateTransition(
                name="product_gate_pending",
                condition=lambda s, p, e: bool(s.context.get("_product_gate_pending")),
                state_factory=...,
                priority=0,
            )
        )
        state_name, session = graph.resolve(session, prompt, extra)
    """

    def __init__(self):
        self._transitions: list[StateTransition] = []

    def add_transition(self, t: StateTransition) -> None:
        """Register a transition, keeping the list sorted by priority."""
        self._transitions.append(t)
        self._transitions.sort(key=lambda x: x.priority)

    @property
    def transitions(self) -> list[StateTransition]:
        """Return registered transitions in priority order."""
        return list(self._transitions)

    def resolve(self, session: Session, prompt: str,
                extra: Optional[dict] = None) -> tuple[str, Session]:
        """Walk transitions in priority order; return (state_name, session).

        Raises:
            ValueError: If no transition matches.
        """
        for t in self._transitions:
            try:
                if t.condition(session, prompt, extra):
                    return t.state_factory(session, prompt, extra)
            except Exception:
                continue
        raise ValueError(
            f"No transition matched for session {session.id} "
            f"(status={session.status}, plan={'exists' if session.get_last_plan() else 'none'})"
        )


def build_default_state_graph() -> StateGraph:
    """Build the standard PlanActFlow state graph with all transitions."""
    from weebot.application.flows.flow_router import FlowRouter

    graph = StateGraph()

    # Priority 0: Product gate clarification pending
    graph.add_transition(
        StateTransition(
            name="product_gate",
            condition=lambda s, p, e: bool(s.context.get("_product_gate_pending")),
            state_factory=lambda s, p, e: FlowRouter._route_product_gate(s, p, e),
            priority=0,
        )
    )

    # Priority 1: Plan pending approval
    graph.add_transition(
        StateTransition(
            name="plan_approval",
            condition=lambda s, p, e: bool(s.context.get("plan_pending_approval")),
            state_factory=lambda s, p, e: FlowRouter._route_plan_approval(s, p, e),
            priority=1,
        )
    )

    # Priority 2: Incomplete plan exists → resume execution
    graph.add_transition(
        StateTransition(
            name="resume_incomplete_plan",
            condition=lambda s, p, e: (
                s.get_last_plan() is not None
                and not s.get_last_plan().is_complete()
            ),
            state_factory=lambda s, p, e: ("ExecutingState", s),
            priority=2,
        )
    )

    # Priority 3: Session was waiting with a plan → resume
    graph.add_transition(
        StateTransition(
            name="resume_waiting_session",
            condition=lambda s, p, e: (
                s.status.name == "WAITING"
                and s.get_last_plan() is not None
            ),
            state_factory=lambda s, p, e: ("ExecutingState", s),
            priority=3,
        )
    )

    # Priority 4: Default — start fresh planning
    graph.add_transition(
        StateTransition(
            name="fresh_planning",
            condition=lambda s, p, e: True,
            state_factory=lambda s, p, e: ("PlanningState", s),
            priority=99,
        )
    )

    return graph
