"""Tests for the Phase 4 guardrail: MAX_SKILL_PROMOTIONS_PER_RUN.

Fully-automatic promotion (SkillReviewGate: quarantined->candidate,
ValidateSkillHandler: candidate->trusted) needed a cap against silent
drift. Both promoters withhold the trust-tier bump once the per-run cap
is reached, while still recording the underlying signal (SkillReview /
positive_uses) that earned it.
"""
from __future__ import annotations

from typing import Optional

import pytest

from weebot.application.cqrs.handlers.validation_handler import ValidateSkillHandler
from weebot.application.cqrs.commands.validation_commands import ValidateSkillCommand
from weebot.application.services.skill_review_gate import SkillReviewGate
from weebot.domain.models.skill import Skill, SkillMetadata, SkillProvenance


_TOPICS = {
    "a": "diagnose flaky pytest fixtures by isolating shared mutable state",
    "b": "rotate leaked cloud credentials after a secret scanner alert",
}


def _quarantined_skill(name: str) -> Skill:
    # Topics share no keywords so distinct skills don't trip the review
    # gate's own keyword-Jaccard near-duplicate rejection.
    topic = _TOPICS[name]
    return Skill(
        name=name,
        description=topic,
        content=f"# procedure\n1. {topic}",
        metadata=SkillMetadata(trust="quarantined"),
    )


def _candidate_skill(name: str, positive_uses: int = 2) -> Skill:
    return Skill(
        name=name,
        description="does a thing",
        content="# steps\n1. do the thing",
        metadata=SkillMetadata(
            trust="candidate",
            provenance=SkillProvenance(positive_uses=positive_uses),
        ),
    )


class _FakeSkillStore:
    """Minimal in-memory SkillStorePort stub — no SkillStorePort ABC needed."""

    def __init__(self, skills: Optional[dict[str, Skill]] = None) -> None:
        self._skills = dict(skills or {})
        self.saved: list[Skill] = []

    async def save(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        self.saved.append(skill)

    async def load(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    async def list_names(self) -> list[str]:
        return list(self._skills.keys())

    async def delete(self, name: str) -> bool:
        return self._skills.pop(name, None) is not None

    async def export_best_md(self, name: str, output_path: str) -> None:
        raise NotImplementedError


class _AlwaysPromoteReviewGate(SkillReviewGate):
    """SkillReviewGate with the LLM call short-circuited to a fixed pass."""

    async def _llm_review(self, skill: Skill):
        return 0.9, 0.9, 0.9, "looks great"


class _FakeValidationRunner:
    def __init__(self, passed: bool = True) -> None:
        self._passed = passed

    async def validate(self, candidate_content, validation_task_ids, harness):
        class _Result:
            passed = self._passed

        return _Result()


class TestSkillReviewGatePromotionCap:
    async def test_promotes_under_cap(self):
        store = _FakeSkillStore()
        gate = _AlwaysPromoteReviewGate(llm=None, skill_store=store, max_promotions_per_run=2)
        skill, review = await gate.apply(_quarantined_skill("a"))
        assert review.promoted is True
        assert skill.metadata.trust == "candidate"
        assert store.saved and store.saved[0].metadata.trust == "candidate"

    async def test_withholds_promotion_once_cap_reached(self):
        store = _FakeSkillStore()
        gate = _AlwaysPromoteReviewGate(llm=None, skill_store=store, max_promotions_per_run=1)

        skill1, review1 = await gate.apply(_quarantined_skill("a"))
        assert skill1.metadata.trust == "candidate"

        skill2, review2 = await gate.apply(_quarantined_skill("b"))
        # Review still says it passed — the cap gates *application*, not judgement.
        assert review2.promoted is True
        assert skill2.metadata.trust == "quarantined"
        assert len(store.saved) == 1


class TestValidateSkillHandlerPromotionCap:
    async def test_promotes_under_cap(self):
        store = _FakeSkillStore({"a": _candidate_skill("a", positive_uses=2)})
        handler = ValidateSkillHandler(
            _FakeValidationRunner(passed=True), skill_store=store, max_promotions_per_run=2,
        )
        result = await handler.handle(
            ValidateSkillCommand(
                skill_name="a", candidate_content="x", validation_task_ids=["t1"],
            )
        )
        assert result.success
        saved = await store.load("a")
        assert saved.metadata.trust == "trusted"

    async def test_withholds_promotion_once_cap_reached(self):
        store = _FakeSkillStore({
            "a": _candidate_skill("a", positive_uses=2),
            "b": _candidate_skill("b", positive_uses=2),
        })
        handler = ValidateSkillHandler(
            _FakeValidationRunner(passed=True), skill_store=store, max_promotions_per_run=1,
        )

        await handler.handle(ValidateSkillCommand(
            skill_name="a", candidate_content="x", validation_task_ids=["t1"],
        ))
        assert (await store.load("a")).metadata.trust == "trusted"

        await handler.handle(ValidateSkillCommand(
            skill_name="b", candidate_content="x", validation_task_ids=["t1"],
        ))
        skill_b = await store.load("b")
        # positive_uses still recorded, but the trust bump was withheld by the cap.
        assert skill_b.metadata.trust == "candidate"
        assert skill_b.metadata.provenance.positive_uses == 3
