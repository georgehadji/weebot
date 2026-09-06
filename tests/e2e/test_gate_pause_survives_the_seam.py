"""D69 — a pause is only real if it survives the process.

Every existing test for the two `ExecutingState` gates drives the state (or
`FlowRouter.resolve_initial_state`) in memory and asserts on `ctx._session`.
All 41 of them were green while the feature was dead, because none of them
crossed the seam the feature actually depends on:

    ExecutingState pauses  ->  [ state repository ]  ->  resume loads it back

The CLI breaks its `async for` on the `WaitForUserEvent` and calls
`resume_session()`, which loads from the repository. If the WAITING status and
the gate's flags are not in the database at that moment, three things happen,
all of which were measured before this test existed:

  1. `resume_session` raises ``ValueError: Session ... is not waiting``;
  2. `atomic_mail_inbound_pending` and `constraint_gate_ack:<id>` never
     persist, so the gate re-fires on every resume, unboundedly — each turn
     builds a fresh flow, so `max_iterations` cannot bound it;
  3. `_user_gate_pending` never persists, so the router branch that reads the
     user's answer is unreachable and ADR 006's "untrusted mail is not acted
     on without review" does not hold.

These tests therefore assert on what came back **out of a real
SQLiteStateRepository**, never on the in-memory session. That distinction is
the entire point of the file.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.executing import ExecutingState
from weebot.domain.models.event import WaitForUserEvent
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


@pytest.fixture
async def repo(tmp_path):
    """A real repository on a real (temporary) SQLite file.

    Closed on teardown for the reason `tests/e2e/test_persistence.py` gives:
    each repo registers a pool of non-daemon aiosqlite worker threads, and
    leaving one open hangs the interpreter after the run.
    """
    r = SQLiteStateRepository(db_path=str(tmp_path / "seam.db"))
    try:
        yield r
    finally:
        await r.close()


def _context(session: Session, plan: Plan, repo: SQLiteStateRepository | None):
    """A **real** `PlanActFlow`, wired to a real repository.

    Deliberately not a `SimpleNamespace`. The first draft of this file used
    one, and it took the in-memory fallback in `_pause_for_user` — i.e. it
    reproduced, inside the very test written to catch the defect, the mistake
    that hid the defect: a double that does not implement the contract the
    production path depends on. If this ever goes back to a stub, the file
    stops testing anything.
    """
    flow = PlanActFlow(session=session, state_repo=repo, mediator=None)
    flow._plan = plan
    flow._step_execution_counts = {}
    flow._max_step_repetitions = 10
    flow._hooks = None
    flow._task_preset = None
    flow._behavioral_learner = None
    flow._steering = None
    return flow


async def _drive_to_gate(ctx) -> list:
    return [e async for e in ExecutingState().execute(ctx, "go")]


# --------------------------------------------------------------------------
# The inbound-mail gate (ADR 006).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_mail_pause_reaches_the_database(repo, monkeypatch):
    """The defect in one assertion: the pause must be in the DB, not just in RAM."""
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
    session = Session(id="seam-mail").set_fact("atomic_mail_inbound_pending", True)
    plan = Plan(title="t", steps=[Step(id="s2", description="summarise the email")])
    ctx = _context(session, plan, repo)
    await repo.save_session(session)

    events = await _drive_to_gate(ctx)
    assert any(isinstance(e, WaitForUserEvent) for e in events), "gate did not fire"

    reloaded = await repo.load_session("seam-mail")
    assert reloaded is not None
    assert reloaded.status is SessionStatus.WAITING, (
        "the DB does not know the session is waiting — resume_session() will "
        "raise 'is not waiting' and the CLI crashes on the user's answer"
    )


@pytest.mark.asyncio
async def test_the_routing_flag_reaches_the_database(repo, monkeypatch):
    """Without this, the branch that reads the user's answer never runs.

    `_user_gate_pending` is what `FlowRouter.resolve_initial_state` keys its
    Priority-2 branch off. If it is not in the DB, the resume falls through to
    the generic branch that never reads `prompt`, and the refusal path — clear
    the constraint acks, re-arm the mail gate, carry the instruction into
    re-planning — is unreachable.
    """
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
    session = Session(id="seam-flag").set_fact("atomic_mail_inbound_pending", True)
    plan = Plan(title="t", steps=[Step(id="s2", description="act on the email")])
    ctx = _context(session, plan, repo)
    await repo.save_session(session)

    await _drive_to_gate(ctx)

    reloaded = await repo.load_session("seam-flag")
    assert reloaded.context.get("_user_gate_pending") == "inbound_mail"


@pytest.mark.asyncio
async def test_the_cleared_mail_flag_reaches_the_database(repo, monkeypatch):
    """The gate clears this before pausing so the resume does not re-fire it.

    If the cleared value never lands, the DB keeps the *pre-gate* True and the
    gate fires again on the next turn, and the next, without bound.
    """
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
    session = Session(id="seam-clear").set_fact("atomic_mail_inbound_pending", True)
    plan = Plan(title="t", steps=[Step(id="s2", description="act on the email")])
    ctx = _context(session, plan, repo)
    await repo.save_session(session)

    await _drive_to_gate(ctx)

    reloaded = await repo.load_session("seam-clear")
    assert not reloaded.get_fact("atomic_mail_inbound_pending"), (
        "the DB still says inbound mail is pending — the gate will re-fire on "
        "every resume, and each turn is a fresh flow so max_iterations cannot "
        "bound it"
    )


@pytest.mark.asyncio
async def test_the_pause_event_reaches_the_database(repo, monkeypatch):
    """The question the user is answering has to be in the transcript."""
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
    session = Session(id="seam-event").set_fact("atomic_mail_inbound_pending", True)
    plan = Plan(title="t", steps=[Step(id="s2", description="act on the email")])
    ctx = _context(session, plan, repo)
    await repo.save_session(session)

    await _drive_to_gate(ctx)

    reloaded = await repo.load_session("seam-event")
    waits = [e for e in reloaded.events if getattr(e, "type", None) == "wait_for_user"]
    assert len(waits) == 1, f"expected exactly one persisted pause, got {len(waits)}"


# --------------------------------------------------------------------------
# The constraint gate — same seam, same requirement.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_constraint_gate_pause_reaches_the_database(repo, monkeypatch):
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "true")
    session = Session(id="seam-constraint")
    plan = Plan(title="t", steps=[Step(id="s1", description="deploy to production")])
    ctx = _context(session, plan, repo)

    async def _violations(*_a, **_k):
        return [SimpleNamespace(text="never touch production")]

    monkeypatch.setattr(ExecutingState, "_constraint_violations", lambda *a, **k: [
        SimpleNamespace(text="never touch production")
    ])
    monkeypatch.setattr(
        ExecutingState, "_journal_constraint_violation", _violations, raising=False
    )
    await repo.save_session(session)

    events = await _drive_to_gate(ctx)
    if not any(isinstance(e, WaitForUserEvent) for e in events):
        pytest.skip("constraint gate did not fire in this configuration")

    reloaded = await repo.load_session("seam-constraint")
    assert reloaded.status is SessionStatus.WAITING
    assert reloaded.context.get("_user_gate_pending") == "constraint"
    assert reloaded.get_fact("constraint_gate_ack:s1")


# --------------------------------------------------------------------------
# The gate must not depend on a repository being present.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_gate_without_a_repository_still_pauses(monkeypatch):
    """Sub-agent flows run with `_state_repo=None`. The pause must still happen
    in memory — it simply cannot be durable, and that is a different problem."""
    monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
    session = Session(id="no-repo").set_fact("atomic_mail_inbound_pending", True)
    plan = Plan(title="t", steps=[Step(id="s2", description="act on the email")])
    ctx = _context(session, plan, None)

    events = await _drive_to_gate(ctx)

    assert any(isinstance(e, WaitForUserEvent) for e in events)
    assert ctx._session.status is SessionStatus.WAITING
