"""D4: `flow recover SESSION_ID` resumes an interrupted run from its checkpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from click.testing import CliRunner

from weebot.domain.models.checkpoint import FlowCheckpoint
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session, SessionStatus


def _checkpoint():
    plan = Plan(
        title="p",
        steps=[
            Step(id="s0", description="a", status=StepStatus.COMPLETED),
            Step(id="s1", description="b"),
        ],
    )
    return FlowCheckpoint(
        session_id="s1", flow_type="PlanActFlow", current_state="executing", plan_snapshot=plan
    )


def _patch(monkeypatch, checkpoint):
    from cli.commands import flow as module

    session = Session(id="s1", user_id="u", agent_id="a").set_status(SessionStatus.FAILED)
    repo = SimpleNamespace(load_session=AsyncMock(return_value=session), save_session=AsyncMock())
    store = SimpleNamespace(load=AsyncMock(return_value=checkpoint))
    resumed = []

    async def resume(session_id, answer):
        resumed.append((session_id, answer))
        if False:
            yield None

    monkeypatch.setattr(module, "_get_state_repo", lambda: repo)
    monkeypatch.setattr(module, "_checkpoint_store", lambda: store)
    monkeypatch.setattr(module, "_resume_inline", resume)
    return module, repo, resumed


def test_recover_restores_the_plan_and_resumes(monkeypatch):
    module, repo, resumed = _patch(monkeypatch, _checkpoint())
    result = CliRunner().invoke(module.flow, ["recover", "s1"])
    assert result.exit_code == 0, result.output
    saved = repo.save_session.await_args.args[0]
    assert saved.status == SessionStatus.WAITING
    assert saved.get_last_plan().steps[0].status == StepStatus.COMPLETED
    assert resumed and resumed[0][0] == "s1"


def test_recover_without_a_checkpoint_refuses(monkeypatch):
    module, repo, resumed = _patch(monkeypatch, None)
    result = CliRunner().invoke(module.flow, ["recover", "s1"])
    assert result.exit_code != 0 and "no checkpoint" in result.output
    assert not resumed
