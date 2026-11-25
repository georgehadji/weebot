"""M1-D2: `Session.set_status` took any target, so the lifecycle was a table nobody enforced.

`_TRANSITIONS` now says which status may follow which, as the writers really behave. An illegal
change logs in production and raises in tests (the conftest turns strict mode on). The cancel
writers also write conditionally, so a session that finished meanwhile is not overwritten.
"""

from __future__ import annotations

import logging
import pathlib
import tempfile

import pytest

from weebot.domain.models.session import (
    _TRANSITIONS,
    IllegalTransition,
    Session,
    SessionAction,
    SessionStatus,
    set_strict_transitions,
)
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

S = SessionStatus

# Every (from, to) a writer performs: the router, the runner, the flows, the repositories.
_LEGAL = [
    (S.PENDING, S.RUNNING),  # TaskRunner._start_direct, FlowRouter
    (S.PENDING, S.WAITING),  # a pause before the first step
    (S.PENDING, S.FAILED),  # a start that cannot begin
    (S.PENDING, S.CANCELLED),  # cancelled while queued
    (S.RUNNING, S.WAITING),  # a pause for the user (approval, question, plan review)
    (S.RUNNING, S.COMPLETED),  # CompletedState
    (S.RUNNING, S.FAILED),  # dead end, crash, interrupted by a restart
    (S.RUNNING, S.CANCELLED),  # cancel
    (S.WAITING, S.RUNNING),  # the user's answer
    (S.WAITING, S.COMPLETED),  # a resumed run ends: the store kept WAITING while it ran
    (S.WAITING, S.FAILED),
    (S.WAITING, S.CANCELLED),
    (S.COMPLETED, S.RUNNING),  # a new task or chat turn in the same session
    (S.FAILED, S.RUNNING),  # a re-run
    (S.FAILED, S.WAITING),  # a checkpoint restore
    (S.CANCELLED, S.RUNNING),  # a re-run
]
_ILLEGAL = [
    (a, b)
    for a in S
    for b in S
    if a is not b and (a, b) not in _LEGAL
]


def test_the_table_lists_exactly_the_writers_transitions():
    listed = {(a, b) for a, targets in _TRANSITIONS.items() for b in targets}
    assert listed == set(_LEGAL)


@pytest.mark.parametrize(("current", "target"), _LEGAL)
def test_a_legal_change_goes_through(current, target):
    assert Session(id="s", status=current).set_status(target).status is target


@pytest.mark.parametrize(("current", "target"), _ILLEGAL)
def test_an_illegal_change_raises_in_strict_mode(current, target):
    with pytest.raises(IllegalTransition, match=f"{current.value} -> {target.value}"):
        Session(id="s", status=current).set_status(target)


@pytest.mark.parametrize("status", list(S))
def test_staying_in_the_same_status_is_always_fine(status):
    assert Session(id="s", status=status).set_status(status).status is status


def test_outside_strict_mode_an_illegal_change_only_logs(caplog):
    previous = set_strict_transitions(False)
    try:
        with caplog.at_level(logging.WARNING, logger="weebot.domain.models.session"):
            moved = Session(id="s", status=S.COMPLETED).set_status(S.FAILED)
    finally:
        set_strict_transitions(previous)
    assert moved.status is S.FAILED, "phase A keeps the write"
    assert "completed -> failed" in caplog.text


@pytest.mark.parametrize("current", [s for s in S if s.allows(SessionAction.CANCEL)])
def test_every_status_that_allows_cancel_may_become_cancelled(current):
    assert S.CANCELLED in _TRANSITIONS[current]


@pytest.mark.parametrize("current", [s for s in S if s.allows(SessionAction.RUN)])
def test_every_status_that_allows_run_may_become_running(current):
    assert S.RUNNING in _TRANSITIONS[current]


def test_a_resume_moves_waiting_to_running():
    assert S.RUNNING in _TRANSITIONS[S.WAITING] and S.WAITING.allows(SessionAction.RESUME)


def _sqlite() -> SQLiteStateRepository:
    return SQLiteStateRepository(db_path=str(pathlib.Path(tempfile.mkdtemp()) / "s.db"))


@pytest.fixture(params=["memory", "sqlite"])
def repo(request):
    return InMemoryStateRepository() if request.param == "memory" else _sqlite()


async def test_a_conditional_status_write_applies_when_the_status_matches(repo):
    await repo.save_session(Session(id="s", status=S.RUNNING))

    wrote = await repo.update_session_status("s", S.CANCELLED, expected=frozenset({S.RUNNING}))

    assert wrote is True
    assert (await repo.load_session("s")).status is S.CANCELLED


async def test_a_conditional_status_write_skips_a_session_that_finished(repo):
    await repo.save_session(Session(id="s", status=S.RUNNING).set_status(S.COMPLETED))

    wrote = await repo.update_session_status(
        "s", S.CANCELLED, expected=SessionStatus.allowing(SessionAction.CANCEL)
    )

    assert wrote is False
    assert (await repo.load_session("s")).status is S.COMPLETED


async def test_a_conditional_write_to_a_missing_session_writes_nothing(repo):
    wrote = await repo.update_session_status("nope", S.CANCELLED, expected=frozenset({S.RUNNING}))
    assert wrote is False
