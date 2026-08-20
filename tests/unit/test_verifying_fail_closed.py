"""Regression tests for VerifyingState's fail-closed behavior (E4),
verifier-tier LLM injection (E6), and domain-state integrity (E7a).

Fixture for the E4/E6 bug: an unreachable/unauthenticated verifier LLM
used to make CoVe verification complete SILENTLY — the task finished,
but "verification_status" was never stamped, so nothing downstream
could tell the difference between "verified" and "never ran".

Fixture for the E7a bug: when CoVe found an inconsistency and revised
the summary, it wrote the revised text back into the executor's own
Step.result via setattr. Step is the same object living in
flow._plan.steps AND in every PlanHistory snapshot already taken
(snapshot() stores a reference, not a copy) — so the rewrite silently
and retroactively corrupted the audit trail.

See tasks/specs/longhorizon_harness_implementation_plan.md (E4/E6/E7).
"""

import httpx
import pytest
from openai import AuthenticationError
from unittest.mock import AsyncMock, MagicMock

from weebot.application.flows.states.completed import CompletedState
from weebot.application.flows.states.verifying import VerifyingState
from weebot.domain.models.audit import AuditDimension, VerificationStatus
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session


def _auth_error() -> AuthenticationError:
    req = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    resp = httpx.Response(401, request=req)
    return AuthenticationError("invalid api key", response=resp, body=None)


def _flow_with_completed_step() -> MagicMock:
    flow = MagicMock()
    flow._verifier_llm = None
    flow._step_audit_service = None
    flow._workspace_snapshots = None  # E7b guard off unless a test wires it
    flow._hooks = None  # MagicMock's auto-attr would be truthy + non-awaitable
    flow._session = Session()
    step = Step(description="do thing", status=StepStatus.COMPLETED, result="did thing")
    flow._plan = Plan(goal="g", steps=[step])
    flow._states: list = []
    flow.set_state = lambda s: flow._states.append(s)
    return flow


async def _run(flow) -> None:
    async for _ in VerifyingState().execute(flow):
        pass


async def _run_state(state: VerifyingState, flow) -> None:
    async for _ in state.execute(flow):
        pass


def _verification_extra(flow) -> dict:
    return dict(getattr(flow._session.context, "extra", {}) or {})


@pytest.mark.asyncio
async def test_auth_error_on_question_generation_stamps_not_run():
    """A dead credential on the very first LLM call must not read as a
    silent pass — it must record NOT_RUN, not just complete quietly."""
    flow = _flow_with_completed_step()
    flow._llm = MagicMock()
    flow._llm.chat = AsyncMock(side_effect=_auth_error())

    await _run(flow)

    assert isinstance(flow._states[-1], CompletedState)
    extra = _verification_extra(flow)
    assert extra.get("verification_status") == "not_run"
    assert extra.get("verification_skip_reason") == "auth_error:question_generation"


@pytest.mark.asyncio
async def test_auth_error_mid_loop_stamps_not_run():
    """Question generation succeeds, but every answer/consistency call
    after it hits an auth wall — must still stamp NOT_RUN, not silently
    complete after exhausting the retry budget."""
    flow = _flow_with_completed_step()
    questions_response = MagicMock(content="Did it work?\nWas it correct?")
    flow._llm = MagicMock()
    flow._llm.chat = AsyncMock(
        side_effect=[questions_response, _auth_error(), _auth_error(), _auth_error(), _auth_error()]
    )

    await _run(flow)

    extra = _verification_extra(flow)
    assert extra.get("verification_status") == "not_run"
    assert extra.get("verification_skip_reason") == "auth_error:answer_loop"


@pytest.mark.asyncio
async def test_non_auth_exception_in_consistency_check_fails_closed():
    """A regular (non-auth) failure must still fail closed as inconsistent
    (E4) — this must NOT regress into propagating like AuthenticationError."""
    flow = MagicMock()
    flow._verifier_llm = None
    flow._llm = MagicMock()
    flow._llm.chat = AsyncMock(side_effect=RuntimeError("transient network error"))

    result = await VerifyingState()._check_consistency(flow, "q", "a", "summary")

    assert result is False


@pytest.mark.asyncio
async def test_non_auth_exception_in_question_generation_returns_empty():
    """Non-auth failures during question generation degrade to skipping
    verification (no questions), not a raised exception."""
    flow = MagicMock()
    flow._verifier_llm = None
    flow._llm = MagicMock()
    flow._llm.chat = AsyncMock(side_effect=RuntimeError("transient network error"))

    result = await VerifyingState()._generate_questions(flow, "summary", 3)

    assert result == []


def test_llm_resolver_prefers_verifier_llm_when_set():
    """LongHorizon-Harness E6: when a cheap-tier verifier LLM is wired,
    verification calls must use it instead of the flow's default model."""
    flow = MagicMock()
    flow._llm = MagicMock(name="default_llm")
    flow._verifier_llm = MagicMock(name="verifier_llm")

    assert VerifyingState._llm(flow) is flow._verifier_llm


def test_llm_resolver_falls_back_when_verifier_llm_is_none():
    flow = MagicMock()
    flow._llm = MagicMock(name="default_llm")
    flow._verifier_llm = None

    assert VerifyingState._llm(flow) is flow._llm


def test_llm_resolver_falls_back_for_legacy_flows_without_the_attribute():
    """Flows constructed before E6 (no _verifier_llm attribute at all)
    must behave exactly as before this change — no AttributeError."""
    flow = MagicMock(spec=["_llm"])
    flow._llm = MagicMock(name="default_llm")

    assert VerifyingState._llm(flow) is flow._llm


@pytest.mark.asyncio
async def test_revision_does_not_mutate_step_result(monkeypatch):
    """E7a: CoVe finding an inconsistency and revising the summary must
    NOT rewrite the executor's own Step.result. The revised text is for
    this method's own downstream use (scoring, gate sweep) only."""
    flow = _flow_with_completed_step()
    flow._llm = MagicMock()
    original_result = flow._plan.steps[0].result

    state = VerifyingState()
    monkeypatch.setattr(
        state, "_generate_questions", AsyncMock(return_value=["Was it done right?"])
    )
    monkeypatch.setattr(state, "_answer_independently", AsyncMock(return_value="Not sure"))
    monkeypatch.setattr(
        state, "_check_consistency", AsyncMock(return_value=False)
    )  # force a revision
    monkeypatch.setattr(state, "_revise_summary", AsyncMock(return_value="LLM-REWRITTEN TEXT"))
    monkeypatch.setattr(
        state,
        "_score_and_revise",
        AsyncMock(
            return_value=("LLM-REWRITTEN TEXT", {"correctness": 5}, VerificationStatus.PASSED)
        ),
    )
    monkeypatch.setattr(state, "_gate_sweep", AsyncMock(return_value=[]))

    await _run_state(state, flow)

    assert flow._plan.steps[0].result == original_result
    assert flow._plan.steps[0].result != "LLM-REWRITTEN TEXT"
    state._revise_summary.assert_awaited_once()  # confirm the revision path actually ran


class _DirtySnapshots:
    """Snapshot port reporting that the workspace changed during the episode."""

    async def snapshot(self):
        from weebot.application.ports.workspace_snapshot_port import WorkspaceSnapshot

        return WorkspaceSnapshot(backend="stub")

    async def diff(self, before):
        from weebot.application.ports.workspace_snapshot_port import WorkspaceDrift

        return WorkspaceDrift(modified=("weebot/domain/models/plan.py",))


@pytest.mark.asyncio
async def test_integrity_is_stamped_not_run_when_no_snapshot_port_is_wired():
    """E7b: an absent guard is NOT_RUN, never an implied pass."""
    flow = _flow_with_completed_step()
    flow._llm = MagicMock()
    flow._llm.chat = AsyncMock(side_effect=_auth_error())

    await _run(flow)

    assert _verification_extra(flow).get("workspace_integrity_status") == "not_run"


@pytest.mark.asyncio
async def test_integrity_is_stamped_on_an_early_return_path():
    """E7b's whole reason for being a context manager.

    The auth-error path returns from deep inside execute(); any check
    written after the episode would simply not run here. If this ever
    regresses to a trailing check, this test is what catches it.
    """
    flow = _flow_with_completed_step()
    flow._workspace_snapshots = _DirtySnapshots()
    flow._llm = MagicMock()
    flow._llm.chat = AsyncMock(side_effect=_auth_error())

    await _run(flow)

    extra = _verification_extra(flow)
    assert extra.get("verification_status") == "not_run"  # the LLM never ran
    assert extra.get("workspace_integrity_status") == "failed"  # but the workspace still moved
    assert any("plan.py" in v for v in extra.get("workspace_integrity_violations", []))


@pytest.mark.asyncio
async def test_integrity_passes_on_a_clean_full_episode(monkeypatch):
    flow = _flow_with_completed_step()
    flow._llm = MagicMock()

    class _CleanSnapshots(_DirtySnapshots):
        async def diff(self, before):
            from weebot.application.ports.workspace_snapshot_port import WorkspaceDrift

            return WorkspaceDrift()

    flow._workspace_snapshots = _CleanSnapshots()

    state = VerifyingState()
    monkeypatch.setattr(state, "_generate_questions", AsyncMock(return_value=["Q?"]))
    monkeypatch.setattr(state, "_answer_independently", AsyncMock(return_value="A"))
    monkeypatch.setattr(state, "_check_consistency", AsyncMock(return_value=True))
    monkeypatch.setattr(
        state,
        "_score_and_revise",
        AsyncMock(return_value=("summary", {"correctness": 5}, VerificationStatus.PASSED)),
    )
    monkeypatch.setattr(state, "_gate_sweep", AsyncMock(return_value=[]))

    await _run_state(state, flow)

    assert _verification_extra(flow).get("workspace_integrity_status") == "passed"


def test_audit_dimension_has_integrity():
    """E7a: the paper's integrity axis — did verification itself corrupt
    the artifact it audited — must be representable, not just a mutation
    bug that leaves no trace in the audit vocabulary."""
    assert AuditDimension.INTEGRITY == "integrity"
