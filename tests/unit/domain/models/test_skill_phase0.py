"""Phase 0 unit tests — trust model, provenance, and lifecycle events."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from weebot.domain.models.skill import (
    Skill,
    SkillMetadata,
    SkillProvenance,
    TrustTier,
)
from weebot.domain.models.event import SkillDistilled, SkillPromoted


# ── SkillProvenance ────────────────────────────────────────────────────────────


class TestSkillProvenance:
    def test_defaults(self):
        p = SkillProvenance()
        assert p.origin == "human"
        assert p.positive_uses == 0
        assert p.session_id is None

    def test_custom_origin(self):
        p = SkillProvenance(origin="distilled", session_id="s1")
        assert p.origin == "distilled"
        assert p.session_id == "s1"

    def test_positive_uses_ge_zero(self):
        with pytest.raises(Exception):
            SkillProvenance(positive_uses=-1)


# ── SkillMetadata trust field ─────────────────────────────────────────────────


class TestSkillMetadataTrust:
    def _meta(self, trust: TrustTier = "trusted") -> SkillMetadata:
        return SkillMetadata(trust=trust)

    def test_default_trust_is_trusted(self):
        assert self._meta().trust == "trusted"

    def test_quarantined_stored(self):
        assert self._meta("quarantined").trust == "quarantined"

    def test_candidate_stored(self):
        assert self._meta("candidate").trust == "candidate"


# ── Skill.is_injectable ────────────────────────────────────────────────────────


class TestSkillIsInjectable:
    def _skill(self, trust: TrustTier) -> Skill:
        return Skill(
            name="test-skill",
            description="desc",
            content="# body",
            metadata=SkillMetadata(trust=trust),
        )

    def test_trusted_is_injectable(self):
        assert self._skill("trusted").is_injectable is True

    def test_candidate_not_injectable(self):
        assert self._skill("candidate").is_injectable is False

    def test_quarantined_not_injectable(self):
        assert self._skill("quarantined").is_injectable is False


# ── Skill.with_trust ──────────────────────────────────────────────────────────


class TestSkillWithTrust:
    def test_returns_new_instance(self):
        s = Skill(name="s", description="", content="", metadata=SkillMetadata(trust="trusted"))
        s2 = s.with_trust("quarantined")
        assert s is not s2

    def test_original_unchanged(self):
        s = Skill(name="s", description="", content="", metadata=SkillMetadata(trust="trusted"))
        s.with_trust("candidate")
        assert s.metadata.trust == "trusted"

    def test_new_tier_applied(self):
        s = Skill(name="s", description="", content="", metadata=SkillMetadata(trust="trusted"))
        assert s.with_trust("quarantined").metadata.trust == "quarantined"


# ── Skill.record_positive_use ─────────────────────────────────────────────────


class TestRecordPositiveUse:
    def _candidate(self, uses: int = 0) -> Skill:
        prov = SkillProvenance(origin="distilled", positive_uses=uses)
        meta = SkillMetadata(trust="candidate", provenance=prov)
        return Skill(name="s", description="", content="", metadata=meta)

    def test_increments_count(self):
        s = self._candidate(uses=0)
        s2 = s.record_positive_use(promotion_threshold=5)
        assert s2.metadata.provenance.positive_uses == 1

    def test_original_count_unchanged(self):
        s = self._candidate(uses=2)
        s.record_positive_use(promotion_threshold=5)
        assert s.metadata.provenance.positive_uses == 2

    def test_promotion_at_threshold(self):
        s = self._candidate(uses=2)
        s2 = s.record_positive_use(promotion_threshold=3)
        assert s2.metadata.trust == "trusted"

    def test_no_promotion_below_threshold(self):
        s = self._candidate(uses=1)
        s2 = s.record_positive_use(promotion_threshold=3)
        assert s2.metadata.trust == "candidate"

    def test_trusted_skill_stays_trusted(self):
        prov = SkillProvenance(origin="human", positive_uses=10)
        meta = SkillMetadata(trust="trusted", provenance=prov)
        s = Skill(name="s", description="", content="", metadata=meta)
        s2 = s.record_positive_use(promotion_threshold=3)
        assert s2.metadata.trust == "trusted"
        assert s2.metadata.provenance.positive_uses == 11


# ── Domain events ─────────────────────────────────────────────────────────────


class TestSkillDistilledEvent:
    def test_fields(self):
        ev = SkillDistilled(
            session_id="sess-1",
            skill_name="my-skill",
            content_preview="# intro",
            origin="distilled",
        )
        assert ev.type == "skill_distilled"
        assert ev.session_id == "sess-1"
        assert ev.skill_name == "my-skill"
        assert isinstance(ev.timestamp, datetime)

    def test_id_auto_generated(self):
        e1 = SkillDistilled(session_id="s", skill_name="n")
        e2 = SkillDistilled(session_id="s", skill_name="n")
        assert e1.id != e2.id


class TestSkillPromotedEvent:
    def test_fields(self):
        ev = SkillPromoted(
            skill_name="my-skill",
            from_tier="quarantined",
            to_tier="candidate",
            positive_uses=0,
        )
        assert ev.type == "skill_promoted"
        assert ev.from_tier == "quarantined"
        assert ev.to_tier == "candidate"

    def test_candidate_to_trusted(self):
        ev = SkillPromoted(
            skill_name="x",
            from_tier="candidate",
            to_tier="trusted",
            positive_uses=3,
        )
        assert ev.positive_uses == 3


# ── Skill round-trip serialisation ───────────────────────────────────────────


class TestSkillSerialisation:
    def test_trust_provenance_round_trip(self):
        prov = SkillProvenance(origin="distilled", session_id="s1", positive_uses=2)
        meta = SkillMetadata(trust="candidate", provenance=prov)
        skill = Skill(name="rt-skill", description="desc", content="# body", metadata=meta)

        json_str = skill.model_dump_json()
        loaded = Skill.model_validate_json(json_str)

        assert loaded.metadata.trust == "candidate"
        assert loaded.metadata.provenance.origin == "distilled"
        assert loaded.metadata.provenance.positive_uses == 2
        assert loaded.metadata.provenance.session_id == "s1"
