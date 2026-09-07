"""Phase 0, quality half — fail open, but never silently.

The decision was split by gate kind: security gates fail closed, quality gates
fail open with a loud, distinguishable marker. A quality gate blocking every
run on its own flaky LLM call is the worse trade. Fabricating a verdict it
never formed is worse still, and that is what all three of these did.

    plan_critic          exception -> overall_confidence=0.8, verdict="approved"
    step_evidence_auditor  three skips -> verdict=PASS, score=1.0, violations=[]
    verifying.py         NOT_RUN written to a key nothing reads

`0.8` is exactly `ConfidentThresholds.WARN_THRESHOLD`, so a critic outage
landed in the HIGHEST routing branch and logged "Plan approved with high
confidence". Against a genuine clean approval the only difference was an empty
`step_scores`, which no caller reads.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.domain.models.plan import Plan, PlanCritique, Step, StepStatus


def _plan() -> Plan:
    return Plan(
        goal="g",
        title="t",
        steps=[Step(id="s1", description="d", status=StepStatus.PENDING)],
    )


class _Boom:
    async def chat(self, **_kwargs):
        raise RuntimeError("provider down")


class _Hang:
    async def chat(self, **_kwargs):
        await asyncio.sleep(30)


# ── plan_critic ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_critic_outage_is_not_an_approval():
    """The defect in one field: `verdict="approved"` from a critic that never ran."""
    from weebot.application.services.plan_critic import PlanCriticService

    critique = await PlanCriticService(_Boom()).critique(_plan(), {})

    assert critique.degraded is True, "a critic that did not run must say so"
    assert critique.verdict != "approved", "it approved a plan it never read"
    assert critique.flaws, "the reason must reach the caller, not just the log"
    assert "RuntimeError" in critique.flaws[0]


@pytest.mark.asyncio
async def test_the_documented_timeout_actually_exists():
    """`_timeout_seconds` was stored in __init__ and never used.

    The constructor docstring promised "Max seconds to wait for the critic LLM
    call. On timeout, the plan proceeds without critique." There was no
    `wait_for` anywhere in the module, so a hung critic held the flow for
    however long the adapter allowed.
    """
    from weebot.application.services.plan_critic import PlanCriticService

    started = asyncio.get_running_loop().time()
    critique = await PlanCriticService(_Hang(), timeout_seconds=0.2).critique(_plan(), {})
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 5.0, f"the documented timeout did not fire ({elapsed:.1f}s)"
    assert critique.degraded is True
    assert "TimeoutError" in critique.flaws[0]


def test_a_real_critique_is_not_marked_degraded():
    """REGRESSION GUARD: the marker must not fire on the healthy path."""
    assert PlanCritique(plan_id="p", verdict="approved", overall_confidence=0.9).degraded is False


@pytest.mark.asyncio
async def test_a_degraded_critique_does_not_route_as_high_confidence(caplog):
    """Routing still proceeds — it is a quality gate — but loudly.

    The old path logged "Plan approved with high confidence" for a critic that
    had never answered.
    """
    import logging
    from types import SimpleNamespace

    from weebot.application.flows.states.critiquing import CritiquingState

    class _DegradedCritic:
        async def critique(self, plan, context):
            return PlanCritique(
                plan_id="t",
                degraded=True,
                overall_confidence=0.8,
                verdict="unreviewed",
                flaws=["Plan critic did not run: RuntimeError. This plan is unreviewed."],
            )

    context = SimpleNamespace(
        _plan=_plan(),
        _tools=[],
        _session=SimpleNamespace(id="s", context=SimpleNamespace(extra={})),
        _task_preset=None,
        _plan_critique=None,
        set_state=lambda state: setattr(context, "_state", state),
        _state=None,
    )

    caplog.set_level(logging.INFO, logger="weebot.application.flows.states.critiquing")
    async for _ in CritiquingState(_DegradedCritic()).execute(context, "task"):
        pass

    assert "high confidence" not in caplog.text, "an outage was logged as an approval"
    assert "UNREVIEWED" in caplog.text
    assert context._plan_critique is not None, "the marker must reach the executor prompt"


# ── step_evidence_auditor ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_pass_with_skipped_checks_is_distinguishable():
    """Three skips produced a PASS byte-identical to a full clean audit.

    This gate is BLOCKING at `executing.py`, so that identical PASS marked the
    step COMPLETED on evidence nobody had checked.
    """
    from weebot.application.services.step_evidence_auditor import StepEvidenceAuditor
    from weebot.domain.models.audit import AuditVerdict
    from weebot.domain.models.event import ToolEvent

    class _FilesThatCannotAnswer:
        async def exists(self, _path):
            return True

        async def size(self, _path):
            raise ValueError("outside the audit root")

        async def read_text(self, _path):
            raise OSError("unreadable")

    auditor = StepEvidenceAuditor(file_storage=_FilesThatCannotAnswer())
    events = [
        ToolEvent(
            tool_name="image_gen",
            status="called",
            function_args={"output_path": "/outside/x.png"},
            result="done",
        )
    ]
    report = await auditor.audit_step(step=None, events=events, session_id="s")

    assert report.verdict == AuditVerdict.PASS, "a quality gate does not block on its own outage"
    assert report.checks_skipped, "but the skip must be recorded, not silent"
    assert "size unavailable" in report.checks_skipped[0]
    assert report.summary != "Evidence supports completion.", (
        "the summary must differ from a full clean audit"
    )


@pytest.mark.asyncio
async def test_a_traversal_no_longer_takes_down_the_flow():
    """`size()` had no guard, so a ValueError propagated out of `audit_step`.

    A gate crashing is neither open nor closed — `PlanActFlow.run` catches only
    `PlanStuckError`, so it took the whole flow with it.
    """
    from weebot.application.services.step_evidence_auditor import StepEvidenceAuditor
    from weebot.domain.models.event import ToolEvent

    class _Traversal:
        async def exists(self, _path):
            return True

        async def size(self, _path):
            raise ValueError("path escapes root_dir")

        async def read_text(self, _path):
            return ""

    events = [
        ToolEvent(
            tool_name="image_gen",
            status="called",
            function_args={"output_path": "../../etc/passwd"},
            result="ok",
        )
    ]
    report = await StepEvidenceAuditor(file_storage=_Traversal()).audit_step(None, events, "s")
    assert report is not None, "the gate raised instead of returning a verdict"


@pytest.mark.asyncio
async def test_a_clean_audit_records_no_skips():
    """REGRESSION GUARD: the marker must stay empty when everything ran."""
    from weebot.application.services.step_evidence_auditor import StepEvidenceAuditor

    report = await StepEvidenceAuditor(file_storage=None).audit_step(None, [], "s")
    assert report.checks_skipped == []
    assert report.summary == "Evidence supports completion."


# ── the stamp ─────────────────────────────────────────────────────────


def test_the_stamp_can_carry_the_verification_status():
    """`verifying.py` wrote NOT_RUN to a key nothing read.

    `SessionStamp` has `model_config = {"extra": "forbid"}` and had no field for
    it, so the marker could not reach the stamp even if a consumer wanted it.
    An empty `gate_failures` means "no gate failed" — which is also what a gate
    that never ran produces.
    """
    from weebot.domain.models.stamp import SessionStamp

    stamp = SessionStamp(verification_status="not_run", gate_failures=[])
    assert stamp.verification_status == "not_run"
    assert SessionStamp().verification_status == ""
