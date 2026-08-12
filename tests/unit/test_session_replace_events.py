"""Session.replace_events() — the _memory_index staleness bug (F3, plan §6.2).

Session._memory_index is a PrivateAttr Pydantic v2 model_copy() carries by
identity, not by the default_factory the old comment claimed. A plain
``model_copy(update={"events": ...})`` after the event list shrinks (e.g.
compaction) leaves the index pointing at stale list positions, and
get_last_plan()/has_unresolved_wait_event() then raise IndexError.

These tests build sessions via ``Session().add_event(...)`` — the constructor
form ``Session(events=[...])`` used elsewhere in this suite leaves
_memory_index empty from the start and cannot see this bug at all.
"""
from __future__ import annotations

from weebot.application.services.memory_compactor import MemoryCompactor
from weebot.domain.models.event import DoneEvent, PlanEvent, ToolEvent, WaitForUserEvent
from weebot.domain.models.plan import Plan
from weebot.domain.models.session import Session


def _build_session_with_repeated_tool_results() -> Session:
    """A session whose compaction shrinks the event list (dedup collapses 5→1)."""
    session = Session(id="replace-events-test")
    session = session.add_event(
        PlanEvent(plan=Plan(title="t", message="m"))
    )
    for i in range(5):
        session = session.add_event(
            ToolEvent(
                tool_call_id=f"tc{i}",
                tool_name="bash",
                function_name="bash",
                function_args={"command": "ls"},
                result="same_output",
            )
        )
    session = session.add_event(WaitForUserEvent(question="continue?"))
    return session


class TestReplaceEvents:
    def test_get_last_plan_survives_index_shrink(self) -> None:
        """Reproduces the reported crash: compaction shrinks events, then
        get_last_plan() must not raise IndexError on the stale index."""
        session = _build_session_with_repeated_tool_results()
        compactor = MemoryCompactor(preserve_constraints=False)
        compacted = compactor.compact_session(session)

        # Dedup collapsed the 5 identical ToolEvents.
        assert len(compacted.events) < len(session.events)

        plan = compacted.get_last_plan()
        assert plan is not None
        assert plan.title == "t"

    def test_has_unresolved_wait_event_survives_index_shrink(self) -> None:
        session = _build_session_with_repeated_tool_results()
        compactor = MemoryCompactor(preserve_constraints=False)
        compacted = compactor.compact_session(session)

        assert compacted.has_unresolved_wait_event() is True

    def test_replace_events_rebuilds_index_from_scratch(self) -> None:
        """The index after replace_events() must reflect the NEW list positions,
        not be inherited from the session it was called on."""
        session = Session(id="rebuild-test")
        session = session.add_event(PlanEvent(plan=Plan(title="old", message="")))
        session = session.add_event(DoneEvent())

        new_plan_event = PlanEvent(plan=Plan(title="new", message=""))
        replaced = session.replace_events([new_plan_event])

        assert replaced.get_last_plan().title == "new"
        # The index must be a fresh object, not the same one as the original.
        assert replaced._memory_index is not session._memory_index

    def test_replace_events_on_empty_list(self) -> None:
        session = Session(id="empty-test").add_event(DoneEvent())
        replaced = session.replace_events([])
        assert replaced.events == []
        assert replaced.get_last_plan() is None
        assert replaced.has_unresolved_wait_event() is False
