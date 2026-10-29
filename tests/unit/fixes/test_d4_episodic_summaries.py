"""D4: successful sessions leave a summary the next similar task is planned with.

The summary repository had no producer, no consumer and no registration, and it
could not be purged when a session was deleted. Now (WEEBOT_EPISODIC_SUMMARIES):
- CompletedState saves a short summary of every fully successful plan;
- PlanningState adds "a similar past task went like this" notes;
- the repository embeds when local embeddings exist and falls back to token
  overlap when they do not, so it works on a default install;
- the session-delete cascade purges it whether or not the flag is on.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.infrastructure.persistence.sqlite_summary_repo import SQLiteSummaryRepository


async def _no_embedding(_text):
    return None


def _repo(tmp_path, monkeypatch):
    from weebot.infrastructure.persistence import sqlite_summary_repo as module

    monkeypatch.setattr(module, "_embed", _no_embedding)
    return SQLiteSummaryRepository(db_path=str(tmp_path / "summaries.db"))


async def test_a_summary_is_found_for_a_similar_task_and_purged_with_its_session(
    tmp_path, monkeypatch
):
    repo = _repo(tmp_path, monkeypatch)
    await repo.save_summary("s1", "build a landing page for a bakery", "Plan: scaffold; style")
    await repo.save_summary("s2", "summarise quarterly sales numbers", "Plan: load csv; chart")

    [(session_id, task, _summary, score)] = await repo.find_similar(
        "build a landing page for a florist", k=1
    )
    assert session_id == "s1" and "bakery" in task and score > 0.3

    assert await repo.delete_by_session_id("s1") == 1
    assert [m[0] for m in await repo.find_similar("build a landing page", k=3)] == ["s2"]


async def test_deleting_before_anything_was_saved_creates_no_file(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    assert await repo.delete_by_session_id("nobody") == 0
    assert not (tmp_path / "summaries.db").exists()


async def test_matches_become_planner_notes():
    from weebot.application.services.episodic_summaries import similar_session_notes

    async def find_similar(text, k):
        return [("s1", "build a bakery site", "scaffold then style", 0.6), ("s2", "x", "y", 0.1)]

    repo = SimpleNamespace(find_similar=find_similar)
    notes = await similar_session_notes(repo, "build a site")
    assert len(notes) == 1 and "bakery" in notes[0] and "scaffold then style" in notes[0]
    assert await similar_session_notes(None, "build a site") == []


def test_only_a_fully_successful_plan_is_summarised():
    from weebot.application.services.episodic_summaries import summarise_plan

    done = Plan(
        title="Bakery site",
        steps=[
            Step(id="1", description="scaffold", status=StepStatus.COMPLETED),
            Step(id="2", description="style", status=StepStatus.COMPLETED, result="looks good"),
        ],
    )
    broken = done.steps[1].model_copy(update={"status": StepStatus.FAILED})
    failed = done.model_copy(update={"steps": [done.steps[0], broken]})
    text = summarise_plan(done)
    assert "Bakery site" in text and "scaffold" in text and "looks good" in text
    assert summarise_plan(failed) is None


def _flow(resolve):
    from weebot.application.flows.flow_builder import build_flow
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import Session

    return build_flow(
        resolve=resolve,
        flow_type="plan_act",
        session=Session(id="s-flow", user_id="u", agent_id="a"),
        llm=MagicMock(),
        tools=ToolCollection(),
        mediator=MagicMock(),
    )


def test_the_flow_gets_the_repository_only_while_the_flag_is_on(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.di.keys import SUMMARY_REPO

    repo = object()

    def resolve(key):
        return repo if key == SUMMARY_REPO else None

    monkeypatch.delenv("WEEBOT_EPISODIC_SUMMARIES", raising=False)
    importlib.reload(flags)
    assert _flow(resolve)._summary_repo is None
    monkeypatch.setenv("WEEBOT_EPISODIC_SUMMARIES", "1")
    importlib.reload(flags)
    try:
        assert _flow(resolve)._summary_repo is repo
    finally:
        monkeypatch.delenv("WEEBOT_EPISODIC_SUMMARIES")
        importlib.reload(flags)


def test_the_delete_cascade_purges_summaries():
    from weebot.application.di.keys import SUMMARY_REPO
    from weebot.interfaces.web.dependencies import _session_stores

    assert ("episodic_summaries", SUMMARY_REPO, "delete_by_session_id") in _session_stores()


def test_completed_and_planning_states_use_it():
    from pathlib import Path

    states = Path("weebot/application/flows/states")
    assert "save_session_summary(" in (states / "completed.py").read_text(encoding="utf-8")
    assert "similar_session_notes(" in (states / "planning.py").read_text(encoding="utf-8")
