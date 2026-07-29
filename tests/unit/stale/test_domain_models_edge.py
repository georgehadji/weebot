"""Edge-case tests for new domain models from HyperAgents implementation."""
from __future__ import annotations

import pytest
from weebot.domain.models.skill_variant import SkillVariant
from weebot.domain.models.prompt_variant import PromptVariant, PromptVariantSource
from weebot.domain.models.self_improvement import ImprovementStrategy
from weebot.domain.models.session import Session, SessionContext


class TestSkillVariantEdgeCases:
    """Edge cases for SkillVariant model."""

    def test_variant_with_max_score(self) -> None:
        v = SkillVariant(score=1.0, domain="coding")
        assert v.score == 1.0

    def test_variant_with_zero_score(self) -> None:
        v = SkillVariant(score=0.0, domain="coding")
        assert v.score == 0.0

    def test_variant_with_negative_children_count(self) -> None:
        """Should accept negative children_count (DB may have bugs)."""
        v = SkillVariant(children_count=-1)
        assert v.children_count == -1

    def test_variant_with_empty_domain(self) -> None:
        v = SkillVariant(domain="")
        assert v.domain == ""

    def test_variant_with_deep_generation(self) -> None:
        v = SkillVariant(generation=999)
        assert v.generation == 999

    def test_created_at_is_set(self) -> None:
        v = SkillVariant()
        assert v.created_at is not None


class TestPromptVariantEdgeCases:
    """Edge cases for PromptVariant model."""

    def test_all_source_enum_values(self) -> None:
        """All PromptVariantSource values should be usable."""
        v1 = PromptVariant(source=PromptVariantSource.HUMAN)
        v2 = PromptVariant(source=PromptVariantSource.SELF_IMPROVER)
        v3 = PromptVariant(source=PromptVariantSource.META_CRITIC)
        assert v1.source == PromptVariantSource.HUMAN
        assert v2.source == PromptVariantSource.SELF_IMPROVER
        assert v3.source == PromptVariantSource.META_CRITIC

    def test_empty_prompt_content(self) -> None:
        v = PromptVariant(prompt_content="")
        assert v.prompt_content == ""

    def test_inactive_by_default(self) -> None:
        v = PromptVariant()
        assert v.is_active is False

    def test_activate_then_deactivate(self) -> None:
        v = PromptVariant(is_active=True)
        assert v.is_active is True
        v2 = v.model_copy(update={"is_active": False})
        assert v2.is_active is False


class TestImprovementStrategyEdgeCases:
    """Edge cases for ImprovementStrategy model."""

    def test_composite_score_with_zero_effectiveness(self) -> None:
        s = ImprovementStrategy(effectiveness_score=0.0, transfer_count=10)
        assert s.composite_score == 0.0

    def test_composite_score_with_max_values(self) -> None:
        s = ImprovementStrategy(effectiveness_score=1.0, transfer_count=100)
        assert s.composite_score == 101.0

    def test_null_target_domain(self) -> None:
        s = ImprovementStrategy(target_domain=None)
        assert s.target_domain is None

    def test_empty_source_domain(self) -> None:
        s = ImprovementStrategy(source_domain="")
        assert s.source_domain == ""

    def test_strategy_with_long_snippet(self) -> None:
        long_text = "x" * 10000
        s = ImprovementStrategy(meta_agent_prompt_snippet=long_text)
        assert len(s.meta_agent_prompt_snippet) == 10000


class TestSessionMetaNotesEdgeCases:
    """Edge cases for SessionContext.meta_notes."""

    def test_add_meta_note_caps_at_twenty(self) -> None:
        session = Session(id="test")
        for i in range(30):
            session = session.add_meta_note(f"Note {i}")
        assert len(session.context.meta_notes) == 20

    def test_add_meta_note_evicts_oldest(self) -> None:
        session = Session(id="test")
        for i in range(21):
            session = session.add_meta_note(f"Note {i}")
        # Note 0 should be evicted, Note 20 should be present
        notes = session.context.meta_notes
        assert "Note 0" not in notes
        assert "Note 20" in notes

    def test_empty_meta_notes_default(self) -> None:
        ctx = SessionContext()
        assert ctx.meta_notes == []

    def test_meta_notes_survive_session_copy(self) -> None:
        session = Session(id="test")
        session = session.add_meta_note("Test note")
        copy = session.model_copy(update={"status": "running"})
        assert "Test note" in copy.context.meta_notes
