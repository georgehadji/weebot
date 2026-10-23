"""The plan under review is a file the user can edit; approve runs the edited file (ICM B2).

The plan used to exist only as terminal text: to change one step the user had
to describe the change and wait for a re-plan. Plan review now writes
`Output/<session>/01_plan.md`; on "approve" an edited step list is the plan
that runs, and an untouched file changes nothing.
"""

from __future__ import annotations

from weebot.application.flows.flow_router import FlowRouter
from weebot.core import plan_file
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, Step
from weebot.domain.models.session import Session


def _waiting_session(tmp_path, monkeypatch):
    monkeypatch.setattr("weebot.core.output_path._PROJECT_ROOT", tmp_path.resolve())
    plan = Plan(title="T", steps=[Step(id="s1", description="Search the web for X"),
                                  Step(id="s2", description="Write a summary")])
    s = Session(id="sess-1").add_event(PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump(mode="json")))
    s = s.model_copy(update={"context": s.context.model_copy(update={"extra": {"plan_pending_approval": True}})})
    return s, plan


def test_the_file_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr("weebot.core.output_path._PROJECT_ROOT", tmp_path.resolve())
    path = plan_file.write("sess-1", "T", ["a", "b"])
    assert path.endswith("01_plan.md") and plan_file.read_steps("sess-1") == ["a", "b"]


def test_approve_runs_the_edited_file(tmp_path, monkeypatch):
    s, plan = _waiting_session(tmp_path, monkeypatch)
    plan_file.write(s.id, plan.title, [st.description for st in plan.steps])
    p = plan_file.path_for(s.id)
    p.write_text(p.read_text(encoding="utf-8").replace("Write a summary", "Write a 3-line summary")
                 + "3. Save it to Output/x/summary.md\n", encoding="utf-8")
    _, routed = FlowRouter.resolve_initial_state(s, "approve", extra=s.context.extra)
    steps = routed.get_last_plan().steps
    assert [st.description for st in steps] == [
        "Search the web for X", "Write a 3-line summary", "Save it to Output/x/summary.md"]
    assert steps[0].id == "s1"  # an unchanged step keeps its id


def test_an_untouched_file_changes_nothing(tmp_path, monkeypatch):
    s, plan = _waiting_session(tmp_path, monkeypatch)
    plan_file.write(s.id, plan.title, [st.description for st in plan.steps])
    _, routed = FlowRouter.resolve_initial_state(s, "approve", extra=s.context.extra)
    assert len(routed.events) == len(s.events)


async def test_plan_review_writes_the_file_and_says_where(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from weebot.application.flows.states.plan_review import PlanReviewState
    from weebot.domain.models.event import WaitForUserEvent

    monkeypatch.setattr("weebot.core.output_path._PROJECT_ROOT", tmp_path.resolve())
    ctx = MagicMock()
    ctx._plan = Plan(title="T", steps=[Step(id="s1", description="one"), Step(id="s2", description="two")])
    ctx._session = Session(id="sess-9")
    ctx._emit = AsyncMock()
    ctx._state_repo = None
    events = [e async for e in PlanReviewState(min_steps=1).execute(ctx, "p")]
    wait = next(e for e in events if isinstance(e, WaitForUserEvent))
    assert "01_plan.md" in wait.question
    assert plan_file.read_steps("sess-9") == ["one", "two"]


async def test_the_edited_plan_is_saved_before_the_first_step_runs(tmp_path, monkeypatch):
    """The step handler reloads the plan from the repo, so an edit kept only in
    memory sends `edited-N` ids it cannot find (STEP_NOT_FOUND)."""
    import types

    from weebot.application.cqrs.base import CommandResult
    from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import SessionStatus

    s, plan = _waiting_session(tmp_path, monkeypatch)
    s = s.set_status(SessionStatus.WAITING)
    plan_file.write(s.id, plan.title, [st.description for st in plan.steps])
    p = plan_file.path_for(s.id)
    p.write_text(p.read_text(encoding="utf-8") + "3. Save it\n", encoding="utf-8")

    saved: dict = {}

    class _Repo:
        async def save_session(self, session):
            saved["s"] = session

        async def load_session(self, sid):
            return saved.get("s")

        def __getattr__(self, name):
            async def _noop(*a, **k):
                return None
            return _noop

    seen: list = []

    class _Mediator:
        async def send(self, cmd):
            stored = saved.get("s")
            seen.append([st.id for st in stored.get_last_plan().steps] if stored else None)
            return CommandResult.fail(error="stop", error_code="TEST_STOP")

    class _LLM:
        async def chat(self, **_):
            return types.SimpleNamespace(content="{}", model="x", usage=None)

    flow = PlanActFlow(PlanActFlowConfig(
        llm=_LLM(), tools=ToolCollection(), session=s, max_iterations=1,
        state_repo=_Repo(), mediator=_Mediator()))
    async for _ in flow.run("approve"):
        pass
    assert seen and seen[0] == ["s1", "s2", "edited-3"]
