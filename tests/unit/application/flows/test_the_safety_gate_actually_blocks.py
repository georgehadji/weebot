"""PH0-6 — a gate that reached the right verdict and nothing enforced it.

`HarnessSafetyGate.check` classifies correctly, including the fail-safe branch:

    else:
        # Unknown surface — treat as gated (fail-safe)
        gated.append(edit)

Its caller then did this:

    if safety_result.requires_approval:
        yield WaitForUserEvent(question=safety_result.approval_prompt)

    saved = await self._target.save(candidate)      # <- next statement

Unconditionally. The comment said "Callers that want to block must stop
iterating after receiving WaitForUserEvent."

**Zero callers did.** `cli/commands/harness.py` iterated with
`if hasattr(event, "message") and event.message`, and `WaitForUserEvent`
carries `question`, not `message` — so the approval prompt was not even
DISPLAYED, and the edit to a safety-critical surface was persisted anyway.

A gate whose enforcement is delegated to every caller is not a gate. The
existing `test_gated_edit_yields_wait_for_user_event` asserted only that the
event was yielded, so it passed against the broken behaviour — the same shape
as the control tests in Phase 0.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.domain.models.failure_signature import FailureCluster, FailureSignature


def _repo_with_one_cluster():
    repo = AsyncMock()
    sig = FailureSignature(
        session_id="s1",
        task_id="t1",
        terminal_cause="timeout",
        agent_behavior="retry_loop",
        mechanism="unproductive_repetition",
        actionability_score=0.8,
    )
    repo.get_clusters.return_value = [FailureCluster.from_signatures([sig])]
    repo.count_trajectories.return_value = 10
    return repo


def _llm_proposing(target_surface: str):
    llm = AsyncMock()
    llm.chat.return_value = MagicMock(
        content=json.dumps(
            {
                "target": target_surface,
                "value": "5",
                "mechanism": "unproductive_repetition",
                "expected_effect": "Fewer retries",
                "risks": [],
            }
        )
    )
    return llm


def _recording_target():
    """A target that records saves instead of writing a real harness file.

    `name` and `content` are set explicitly: an AsyncMock auto-creates them as
    child mocks, and `_propose_edits` feeds `self._target.name` into a Pydantic
    field typed `str`.
    """
    target = AsyncMock()
    target.name = "test-harness"
    target.content = "instructions: {}"
    target.load.return_value = MagicMock(version="0.2.0")
    target.apply_edits.return_value = MagicMock(version="0.2.1")
    target.save.return_value = MagicMock(version="0.2.1")
    return target


async def _run(target_surface: str):
    from weebot.application.flows.harness_opt_flow import HarnessOptFlow
    from weebot.application.services.regression_gate import RegressionGate

    target = _recording_target()
    flow = HarnessOptFlow(
        llm=_llm_proposing(target_surface),
        target=target,
        trajectory_repo=_repo_with_one_cluster(),
        held_in_tasks=["t1"],
        max_proposals=1,
        gate=RegressionGate(auto_accept=True),
    )
    events = [event async for event in flow.run()]
    return flow, target, events


@pytest.mark.asyncio
async def test_a_gated_edit_is_not_saved():
    """The defect in one assertion: `save` was called for a gated surface.

    `runtime_control.*` is explicitly safety-critical, and the regression gate
    here accepts everything — which is precisely the situation the safety gate
    exists for.
    """
    flow, target, events = await _run("runtime_control.max_recent_tool_errors")

    assert any(type(e).__name__ == "WaitForUserEvent" for e in events), (
        "the approval prompt must still be emitted"
    )
    assert target.save.await_count == 0, (
        "a safety-critical edit was persisted without approval"
    )
    assert [e.target_surface for e in flow.held_for_approval()] == [
        "runtime_control.max_recent_tool_errors"
    ]


@pytest.mark.asyncio
async def test_an_unknown_surface_is_held_too():
    """`check` gates an unrecognised surface fail-safe. So must the flow.

    The classification was already right; nothing acted on it.
    """
    flow, target, events = await _run("something.nobody.declared")

    assert target.save.await_count == 0, "an unrecognised surface was auto-promoted"
    assert flow.held_for_approval(), "the hold must be reportable, not just logged"


@pytest.mark.asyncio
async def test_an_autonomous_edit_is_still_applied():
    """REGRESSION GUARD: the whole point of the loop is unattended promotion
    of the surfaces that are safe to promote. Blocking those would make the
    fix worse than the defect."""
    flow, target, events = await _run("trajectory.repetition_threshold")

    assert target.save.await_count == 1, "an autonomous edit must still be applied"
    assert flow.held_for_approval() == []
    assert not any(type(e).__name__ == "WaitForUserEvent" for e in events)


@pytest.mark.asyncio
async def test_the_hold_is_reported_in_a_field_the_cli_reads():
    """`WaitForUserEvent` has `question`, not `message`.

    The CLI filtered on `message`, so the prompt was dropped entirely. This
    pins the field name the fix depends on — if the event ever grows a
    `message`, the CLI branch order matters and this fails first.
    """
    from weebot.domain.models.event import WaitForUserEvent

    event = WaitForUserEvent(question="Approve?")
    assert event.question == "Approve?"
    assert not hasattr(event, "message")
