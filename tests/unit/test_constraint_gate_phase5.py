"""Tests for the Phase 5 constraint-enforcement gate.

Covers the three defects the audit measured in ExecutingState's gate
(tasks/specs/side_constraint_integrity_plan.md Phase 5.4):

1. pinned to the first prompt -- a constraint stated on a later turn never
   reached the gate;
2. false positives -- substring/stopword matching fired on benign steps;
3. inversion -- a LOOSEN constraint ("don't ask me to confirm") made the gate
   pause to ask for confirmation.

Plus the resume defect: the gate cleared nothing, so on resume it re-fired
against the same step and the user could never get past it.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

from weebot.application.flows.states.executing import ExecutingState
from weebot.application.services.constraint_compilers import compile_enforceable
from weebot.application.services.constraint_extractor import ConstraintExtractor
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session
from weebot.domain.models.session_constraint import (
    ConstraintDirection,
    ConstraintKind,
    SessionConstraint,
    SessionConstraintRegistry,
)


def _sc(text: str, *, kind=ConstraintKind.ACTION, direction=ConstraintDirection.TIGHTEN):
    return SessionConstraint(
        text=text, evidence_span=text, kind=kind, direction=direction,
    )


class _FakeFlow:
    """Minimal PlanActFlow stand-in for the gate's duck-typed reads."""

    def __init__(self, registry=None, session=None, journal=None):
        self._session_constraints = registry
        self._session = session or Session(id="s1")
        self._misalignment_journal = journal


class TestCompileEnforceable:
    def test_none_registry_compiles_to_nothing(self):
        assert compile_enforceable(None) == []

    def test_tighten_action_compiles(self):
        reg = SessionConstraintRegistry(constraints=[_sc("never delete the user pool")])
        compiled = compile_enforceable(reg)
        assert len(compiled) == 1
        assert compiled[0].text == "never delete the user pool"
        assert compiled[0].priority == 2

    def test_loosen_never_compiles(self):
        """Paper SC#1 -- the inversion that made the gate self-violating."""
        reg = SessionConstraintRegistry(constraints=[
            _sc("don't ask me to confirm before running commands",
                direction=ConstraintDirection.LOOSEN),
        ])
        assert compile_enforceable(reg) == []

    def test_unjudgeable_kinds_do_not_compile(self):
        """PROCESS/PREFERENCE/OUTPUT are prompt-delivered, not step-gated."""
        reg = SessionConstraintRegistry(constraints=[
            _sc("never use imperial units", kind=ConstraintKind.PREFERENCE),
            _sc("never answer without checking the docs", kind=ConstraintKind.PROCESS),
            _sc("never reply in prose", kind=ConstraintKind.OUTPUT),
        ])
        assert compile_enforceable(reg) == []

    def test_information_kind_compiles(self):
        reg = SessionConstraintRegistry(constraints=[
            _sc("never put my phone number in a file", kind=ConstraintKind.INFORMATION),
        ])
        assert len(compile_enforceable(reg)) == 1

    def test_revoked_constraint_does_not_compile(self):
        reg = SessionConstraintRegistry(constraints=[_sc("never delete files")])
        assert compile_enforceable(reg.revoke("never delete files")) == []


class TestCheckStepFalsePositives:
    """Defect 2: substring and stopword matching fired on benign steps."""

    def _e(self):
        return ConstraintExtractor()

    def test_substring_match_does_not_fire(self):
        """'all' inside 'install' is not evidence of a violation."""
        e = self._e()
        constraints = e.extract("do not delete all logs")
        assert e.check_step("Install the packages", constraints) == []

    def test_stopwords_alone_do_not_reach_quorum(self):
        e = self._e()
        constraints = e.extract("do not touch the billing module")
        assert e.check_step("Update the README with the new notes", constraints) == []

    def test_single_incidental_word_is_not_enough(self):
        e = self._e()
        constraints = e.extract("never modify the production database schema")
        # Shares only "database" -- one content token out of four.
        assert e.check_step("Read the database connection string", constraints) == []

    def test_genuine_violation_still_fires(self):
        e = self._e()
        constraints = e.extract("never modify the production database schema")
        assert e.check_step("Modify the production database schema", constraints)

    def test_plural_singular_still_matches(self):
        e = self._e()
        constraints = e.extract("never expose API keys in logs")
        assert e.check_step("Print API key to logs for debugging", constraints)


class TestGateSourceSelection:
    def test_registry_beats_original_task(self):
        """Defect 1: a constraint stated after turn 1 must reach the gate."""
        session = Session(id="s1").set_fact("original_task", "build me a website")
        reg = SessionConstraintRegistry(constraints=[_sc("never delete the user pool")])
        flow = _FakeFlow(registry=reg, session=session)
        step = Step(id="s1", description="Delete the user pool entries")

        violations = ExecutingState._constraint_violations(flow, step, "")
        assert len(violations) == 1
        assert violations[0].text == "never delete the user pool"

    def test_falls_back_to_legacy_source_when_registry_empty(self):
        flow = _FakeFlow(registry=None, session=Session(id="s1"))
        step = Step(id="s1", description="Delete the user pool entries")

        # No registry -> the prompt argument is the legacy fallback source.
        assert ExecutingState._constraint_violations(
            flow, step, "do not delete the user pool"
        )

    def test_loosen_registry_does_not_gate(self):
        """Defect 3 end to end: the gate must not pause on a LOOSEN constraint."""
        reg = SessionConstraintRegistry(constraints=[
            _sc("don't ask me to confirm before running commands",
                direction=ConstraintDirection.LOOSEN),
        ])
        flow = _FakeFlow(registry=reg, session=Session(id="s1"))
        step = Step(id="s1", description="Run the deploy command")

        assert ExecutingState._constraint_violations(flow, step, "") == []

    def test_env_kill_switch_respected(self, monkeypatch):
        monkeypatch.setenv("CONSTRAINT_CHECK_ENABLED", "false")
        reg = SessionConstraintRegistry(constraints=[_sc("never delete the user pool")])
        flow = _FakeFlow(registry=reg, session=Session(id="s1"))
        step = Step(id="s1", description="Delete the user pool entries")

        assert ExecutingState._constraint_violations(flow, step, "") == []


class TestJournalWrite:
    async def test_journal_is_awaited(self):
        journal = AsyncMock()
        flow = _FakeFlow(session=Session(id="s1"), journal=journal)
        step = Step(id="s1", description="Delete the user pool")

        await ExecutingState._journal_constraint_violation(flow, step, "never delete")

        journal.record.assert_awaited_once()
        entry = journal.record.call_args.args[0]
        assert entry.symptom == "constraint_violation"
        assert entry.constraint_text == "never delete"

    async def test_journal_failure_does_not_raise(self):
        journal = AsyncMock()
        journal.record.side_effect = RuntimeError("journal exploded")
        flow = _FakeFlow(session=Session(id="s1"), journal=journal)
        step = Step(id="s1", description="Delete the user pool")

        # Must not propagate -- the gate is not allowed to fail on telemetry.
        await ExecutingState._journal_constraint_violation(flow, step, "never delete")

    async def test_no_journal_is_a_noop(self):
        flow = _FakeFlow(session=Session(id="s1"), journal=None)
        step = Step(id="s1", description="anything")
        await ExecutingState._journal_constraint_violation(flow, step, "x")


class TestGateOneShot:
    """The resume defect: the gate cleared nothing and re-fired forever."""

    async def test_ack_fact_set_before_pause(self):
        from weebot.domain.models.event import WaitForUserEvent

        reg = SessionConstraintRegistry(constraints=[_sc("never delete the user pool")])
        step = Step(id="st1", description="Delete the user pool entries")

        flow = _FakeFlow(registry=reg, session=Session(id="s1"))
        flow._plan = Plan(title="t", message="m", steps=[step])
        flow._steering = None
        flow._behavioral_learner = None

        events = []
        async for e in ExecutingState().execute(flow, ""):
            events.append(e)

        assert any(isinstance(e, WaitForUserEvent) for e in events)
        # The one-shot ack must be recorded so resume gets past this step.
        assert flow._session.get_fact("constraint_gate_ack:st1") is True

    def test_acked_step_is_not_re_gated(self):
        reg = SessionConstraintRegistry(constraints=[_sc("never delete the user pool")])
        step = Step(id="st1", description="Delete the user pool entries")
        session = Session(id="s1").set_fact("constraint_gate_ack:st1", True)
        flow = _FakeFlow(registry=reg, session=session)

        # The step still violates -- the ack is what suppresses the pause.
        assert ExecutingState._constraint_violations(flow, step, "")
        assert flow._session.get_fact("constraint_gate_ack:st1") is True
