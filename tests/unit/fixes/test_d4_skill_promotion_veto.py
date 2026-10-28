"""D4: chain of verification can veto a skill's promotion to trusted.

Live use counting promotes a candidate after three passing sessions. The promotion
gate meant to check it had no caller and could not pass: it read a `.score` the
verification result did not have, and awaited a scorer that is synchronous. Chain
of verification also treated an unparseable cross-check reply as "verified, no
inconsistencies", with the garbage as the corrected text.

The gate is a veto only (WEEBOT_SKILL_PROMOTION_GATE): it never promotes, and it
blocks only a skill whose claims are contradicted. A procedural skill with nothing
checkable passes; a gate that cannot run keeps the skill a candidate.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from weebot.application.services.chain_of_verification import (
    ChainOfVerificationService,
    CoVeResult,
)
from weebot.domain.models.skill import Skill, SkillMetadata, SkillProvenance
from weebot.domain.services.skill_promotion_gate import SkillPromotionGate


def _llm(*replies):
    return SimpleNamespace(
        chat=AsyncMock(side_effect=[SimpleNamespace(content=r) for r in replies])
    )


async def test_an_unparseable_cross_check_is_not_verified():
    llm = _llm('["Is X true?"]', "yes", "not json at all")
    result = await ChainOfVerificationService(llm).verify("q", "response")
    assert result.verified is False
    assert "unparseable" in result.reason
    assert result.corrected_response == "response"


async def test_the_score_is_the_share_of_consistent_answers():
    cross = '{"inconsistencies": [{"claim": "a"}], "corrected_response": "fixed"}'
    llm = _llm('["q1?", "q2?", "q3?", "q4?"]', "a1", "a2", "a3", "a4", cross)
    result = await ChainOfVerificationService(llm).verify("q", "response")
    assert result.verified and result.questions == 4
    assert result.score == 0.75


def _skill(content="steps", trust="candidate"):
    return Skill(
        name="deploy-site",
        description="how to deploy",
        content=content,
        metadata=SkillMetadata(trust=trust, provenance=SkillProvenance(origin="distilled")),
    )


def _gate(result=None, raises=None):
    verify = AsyncMock(side_effect=raises) if raises else AsyncMock(return_value=result)
    return SkillPromotionGate(chain_of_verification=SimpleNamespace(verify=verify))


async def test_a_contradicted_skill_is_vetoed():
    result = CoVeResult("x", [{}, {}], verified=True, questions=4)
    assert (await _gate(result).evaluate(_skill())).passed is False


async def test_a_consistent_skill_passes():
    result = CoVeResult("x", [], verified=True, questions=3)
    assert (await _gate(result).evaluate(_skill())).passed is True


async def test_a_skill_with_nothing_checkable_passes():
    result = CoVeResult("x", [], verified=False, reason="no questions generated")
    assert (await _gate(result).evaluate(_skill())).passed is True


async def test_a_gate_that_cannot_run_fails_closed():
    broken = CoVeResult("x", [], verified=False, reason="cross-check failed")
    assert (await _gate(broken).evaluate(_skill())).passed is False
    assert (await _gate(raises=RuntimeError("down")).evaluate(_skill())).passed is False


class _Store:
    def __init__(self, skill):
        self.skills = {skill.name: skill}

    async def load(self, name):
        return self.skills.get(name)

    async def save(self, skill):
        self.skills[skill.name] = skill


async def _promote(gate):
    from weebot.application.cqrs.commands.validation_commands import RecordSkillUseCommand
    from weebot.application.cqrs.handlers.validation_handler import RecordSkillUseHandler

    store = _Store(_skill())
    handler = RecordSkillUseHandler(skill_store=store, promotion_gate=gate)
    for session in ("s1", "s2", "s3", "s4"):
        await handler.handle(
            RecordSkillUseCommand(
                skill_name="deploy-site", session_id=session, step_id="1", passed=True
            )
        )
    return store.skills["deploy-site"].metadata.trust


def _verdict_gate(passed=None, raises=None):
    if raises:
        return SimpleNamespace(evaluate=AsyncMock(side_effect=raises))
    verdict = SimpleNamespace(passed=passed, detail="x")
    return SimpleNamespace(evaluate=AsyncMock(return_value=verdict))


async def test_a_vetoed_skill_stays_a_candidate_and_is_checked_once():
    gate = _verdict_gate(passed=False)
    assert await _promote(gate) == "candidate"
    gate.evaluate.assert_awaited_once()


async def test_a_passing_gate_lets_the_promotion_through():
    assert await _promote(_verdict_gate(passed=True)) == "trusted"


async def test_a_raising_gate_keeps_the_skill_a_candidate():
    assert await _promote(_verdict_gate(raises=RuntimeError("boom"))) == "candidate"


def test_the_gate_is_built_only_when_its_flag_is_on(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.di import Container

    container = Container()
    monkeypatch.setattr(container, "_create_llm_for_role", lambda role: _llm())

    monkeypatch.delenv("WEEBOT_SKILL_PROMOTION_GATE", raising=False)
    importlib.reload(flags)
    assert container._create_skill_promotion_gate() is None

    monkeypatch.setenv("WEEBOT_SKILL_PROMOTION_GATE", "1")
    importlib.reload(flags)
    try:
        assert isinstance(container._create_skill_promotion_gate(), SkillPromotionGate)
    finally:
        monkeypatch.delenv("WEEBOT_SKILL_PROMOTION_GATE")
        importlib.reload(flags)


def test_the_live_mediator_passes_the_gate_to_the_use_counter():
    from pathlib import Path

    di = Path("weebot/application/di/__init__.py").read_text(encoding="utf-8")
    handlers = Path("weebot/application/cqrs/handlers/__init__.py").read_text(encoding="utf-8")
    assert "skill_promotion_gate=self._maybe_get(SKILL_PROMOTION_GATE)" in di
    assert "promotion_gate=skill_promotion_gate" in handlers


def test_the_gate_and_the_service_agree_on_nothing_to_check():
    from weebot.application.services.chain_of_verification import NO_CLAIMS_REASON
    from weebot.domain.services.skill_promotion_gate import NOTHING_TO_CHECK

    assert NOTHING_TO_CHECK == NO_CLAIMS_REASON
