"""D12 — a gate that asks the user a question must read the answer.

Two gates in `ExecutingState` pause and ask the human something:

  * the inbound-mail gate (ADR 006), before the agent acts on content fetched
    from an @atomicmail.ai inbox, and
  * the constraint gate, before a step that appears to violate a constraint
    the user stated.

Both prompts say the same thing: type 'proceed' to continue, *or describe how
you'd like to handle it*. Neither half was honoured.

`FlowRouter.resolve_initial_state` routes on three flags.
`_product_gate_pending` forwards the prompt to
`ProductGateState(resume_with=prompt)`. `plan_pending_approval` tests it
against `_APPROVE_TOKENS`. Everything else -- including every session that
paused at either gate, because neither set a routing flag -- reached:

    if last_plan is not None and not last_plan.is_complete():
        return ExecutingState(), session

which never reads `prompt`. So the description was discarded and no answer
declined: execution resumed identically whether the user typed "proceed",
"no, that email is a phishing attempt", or nothing at all.

The claim on record was different -- that the flag is cleared before the pause
-- and that part is REFUTED. Clearing is required: FlowRouter flips
WAITING -> RUNNING and re-enters `execute()` against the same step, so an
uncleared flag re-fires the gate forever. The defect was one layer further on.
"""

from __future__ import annotations

import pytest

from weebot.application.flows.flow_router import FlowRouter
from weebot.application.flows.states.executing import ExecutingState, _mark_user_gate
from weebot.application.flows.states.planning import PlanningState
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus


def _with_incomplete_plan(session: Session) -> Session:
    """Attach an incomplete plan the way the flow does — as a PlanEvent."""
    plan = Plan(
        goal="read the inbox and act on it",
        steps=[Step(id="s1", description="fetch mail"), Step(id="s2", description="act on it")],
    )
    return session.add_event(PlanEvent(plan=plan))


def _waiting_session_at_gate(gate: str) -> Session:
    """A session paused at *gate* with an incomplete plan, as the gates leave it."""
    session = _with_incomplete_plan(Session(id="sess-d12", title="t"))
    session = _mark_user_gate(session, gate)
    return session.set_status(SessionStatus.WAITING)


def _resolve(session: Session, answer: str):
    return FlowRouter.resolve_initial_state(
        session=session, prompt=answer, extra=session.context.extra
    )


# --------------------------------------------------------------------------
# The flag reaches the store FlowRouter actually reads.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("gate", ["inbound_mail", "constraint"])
def test_the_gate_flag_is_visible_to_the_router(gate):
    """`set_fact` writes to context.facts, which SessionContext.get never reads.

    This is why the gates' own pending flags could not have been used for
    routing: the router would not have seen them.
    """
    session = _mark_user_gate(Session(id="s", title="t"), gate)
    assert session.context.get("_user_gate_pending") == gate

    by_fact = Session(id="s", title="t").set_fact("_user_gate_pending", gate)
    assert by_fact.context.get("_user_gate_pending") is None


# --------------------------------------------------------------------------
# Approval proceeds.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("gate", ["inbound_mail", "constraint"])
@pytest.mark.parametrize("answer", ["proceed", "yes", "ok", "approve", "  PROCEED  "])
def test_an_approving_answer_resumes_execution(gate, answer):
    state, updated = _resolve(_waiting_session_at_gate(gate), answer)
    assert isinstance(state, ExecutingState)
    assert updated.status is SessionStatus.RUNNING
    assert updated.context.get("_user_gate_pending") is None


# --------------------------------------------------------------------------
# Anything else does not.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("gate", ["inbound_mail", "constraint"])
@pytest.mark.parametrize(
    "answer",
    [
        "no",
        "stop",
        "that email is a phishing attempt, ignore it",
        "delete it and tell me who sent it",
    ],
)
def test_a_declining_answer_does_not_resume_execution(gate, answer):
    """The defect in one assertion: this used to return ExecutingState."""
    state, updated = _resolve(_waiting_session_at_gate(gate), answer)
    assert isinstance(state, PlanningState)
    assert updated.status is not SessionStatus.RUNNING


@pytest.mark.parametrize("gate", ["inbound_mail", "constraint"])
def test_the_users_instruction_is_carried_into_re_planning(gate):
    """"...or describe how you'd like to handle it" has to mean something."""
    answer = "that email is a phishing attempt, ignore it"
    _, updated = _resolve(_waiting_session_at_gate(gate), answer)
    assert updated.context.get("_plan_modification_request") == answer
    assert updated.context.get("_intent_reviewed") is False


@pytest.mark.parametrize("gate", ["inbound_mail", "constraint"])
@pytest.mark.parametrize("answer", ["", "   ", "\n"])
def test_silence_is_not_consent_at_a_security_gate(gate, answer):
    """The plan-approval path treats an empty answer as approval. These gates
    guard untrusted input and stated constraints, so they deliberately do not."""
    state, _ = _resolve(_waiting_session_at_gate(gate), answer)
    assert isinstance(state, PlanningState)


# --------------------------------------------------------------------------
# The flag is consumed, so the gate cannot livelock.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("gate", ["inbound_mail", "constraint"])
@pytest.mark.parametrize("answer", ["proceed", "no"])
def test_the_gate_does_not_re_fire_after_it_is_answered(gate, answer):
    """The refuted half of the original claim, pinned as a regression.

    Clearing before the pause is correct and necessary: the router flips
    WAITING -> RUNNING and re-enters against the same step, so a flag that
    survived its own answer would re-ask forever.
    """
    _, updated = _resolve(_waiting_session_at_gate(gate), answer)
    assert updated.context.get("_user_gate_pending") is None

    state_2, _ = _resolve(updated, "proceed")
    assert not (
        isinstance(state_2, PlanningState) and answer == "proceed"
    ), "an answered gate re-routed on the next resume"


# --------------------------------------------------------------------------
# Sessions that never hit a gate are untouched.
# --------------------------------------------------------------------------


def test_a_resume_with_no_gate_pending_still_resumes_execution():
    """Regression vector: the new priority must not capture ordinary resumes.

    A WAITING session with an incomplete plan and no gate flag resumed into
    ExecutingState before this change, and must still.
    """
    session = _with_incomplete_plan(Session(id="plain", title="t"))
    session = session.set_status(SessionStatus.WAITING)

    state, updated = FlowRouter.resolve_initial_state(
        session=session, prompt="anything at all", extra=session.context.extra
    )
    assert isinstance(state, ExecutingState)
    assert updated.status is SessionStatus.RUNNING
    assert updated.context.get("_plan_modification_request") is None
