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


@pytest.mark.parametrize("gate", ["inbound_mail", "constraint"])
@pytest.mark.parametrize("answer", ["no", "use staging instead"])
def test_a_decline_leaves_the_session_runnable(gate, answer):
    """Re-planning is useless if the run loop stops before it happens.

    `PlanActFlow.run()` breaks on WAITING, and both gates leave the session
    WAITING before they pause. Returning PlanningState without flipping to
    RUNNING re-plans exactly once and then halts, so the user is shown a new
    plan and nothing after it. The first version of this test asserted
    `status is not RUNNING`, which pinned that bug instead of catching it.
    """
    _, updated = _resolve(_waiting_session_at_gate(gate), answer)
    assert updated.status is SessionStatus.RUNNING


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

    # The first version of this was `assert not (isinstance(state_2,
    # PlanningState) and answer == "proceed")`, which is vacuously true for
    # answer="no" — the half where a surviving flag would actually re-route.
    # Asserting the positive covers both parametrisations and is stronger.
    state_2, _ = _resolve(updated, "proceed")
    assert isinstance(
        state_2, ExecutingState
    ), "an answered gate re-routed on the next resume"


# --------------------------------------------------------------------------
# A decline must not disarm the gate it declined.
# --------------------------------------------------------------------------


def test_declining_clears_the_per_step_constraint_acks():
    """Step ids are positional, so acks cannot outlive their plan.

    `planner.py` numbers steps `step-N`, and the ack is a session fact that
    survives re-planning. Left in place, a re-planned `step-3` inherits the
    old `step-3`'s ack and executes with no gate — the user is never asked
    about the step that actually runs, having just refused its predecessor.
    """
    session = _waiting_session_at_gate("constraint").set_fact(
        "constraint_gate_ack:step-2", True
    )
    _, updated = _resolve(session, "no, never touch production")
    assert not updated.get_fact("constraint_gate_ack:step-2")


def test_declining_the_mail_gate_re_arms_it():
    """The fetched message is still in the transcript and is about to be fed
    to the planner, so the new plan's first step has to be gated again.

    The gate clears `atomic_mail_inbound_pending` before pausing, which is
    right for approval and wrong for a refusal: declining would otherwise
    *widen* the untrusted content's reach — it shapes the next plan — while
    removing the only check that guarded it.
    """
    session = _waiting_session_at_gate("inbound_mail").set_fact(
        "atomic_mail_inbound_pending", False
    )
    _, updated = _resolve(session, "that email is a phishing attempt, ignore it")
    assert updated.get_fact("atomic_mail_inbound_pending") is True


def test_approving_does_not_re_arm_the_mail_gate():
    """The converse: approval is consent, and must not re-ask on every step."""
    session = _waiting_session_at_gate("inbound_mail").set_fact(
        "atomic_mail_inbound_pending", False
    )
    _, updated = _resolve(session, "proceed")
    assert not updated.get_fact("atomic_mail_inbound_pending")


def test_unrelated_context_survives_when_the_caller_omits_extra():
    """`{**(extra or {}), ...}` replaces context.extra wholesale.

    The two pre-existing branches share that shape, so a caller invoking
    resolve_initial_state without the kwarg silently erases task_route and
    every other key. Latent today because the one production caller passes
    it; this branch merges instead.
    """
    session = _waiting_session_at_gate("constraint")
    session = session.model_copy(
        update={
            "context": session.context.model_copy(
                update={"extra": {**session.context.extra, "task_route": "coding"}}
            )
        }
    )
    _, updated = FlowRouter.resolve_initial_state(session=session, prompt="proceed")
    assert updated.context.get("task_route") == "coding"


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
