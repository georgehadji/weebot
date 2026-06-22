"""Tests for governed skill loop — ProposalTracker, SkillReviewGate, SkillPromotionGate, consolidation."""
from __future__ import annotations

import pytest

from weebot.application.services.proposal_tracker import ProposalTracker
from weebot.domain.models.skill import SkillReview, SkillPromotionResult
from weebot.application.services.skill_curator import _extract_keywords, _keyword_overlap


# ── ProposalTracker ──────────────────────────────────────────────────────────

class TestProposalTracker:
    def test_fingerprint_stable(self):
        """Same body produces same fingerprint."""
        fp1 = ProposalTracker.fingerprint("do x then y")
        fp2 = ProposalTracker.fingerprint("do x then y")
        assert fp1 == fp2

    def test_fingerprint_normalises_whitespace(self):
        """Whitespace differences don't change the fingerprint."""
        fp1 = ProposalTracker.fingerprint("do  x   then\ny")
        fp2 = ProposalTracker.fingerprint("do x then y")
        assert fp1 == fp2

    def test_first_proposal_proceeds(self):
        """First proposal of a fingerprint returns True."""
        tracker = ProposalTracker(suppression_threshold=3)
        fp = ProposalTracker.fingerprint("unique skill")
        assert tracker.record_and_check(fp) is True

    def test_repeated_proposals_suppressed(self):
        """At N identical proposals (threshold=3), returns False."""
        tracker = ProposalTracker(suppression_threshold=3)
        fp = ProposalTracker.fingerprint("repeated skill")
        assert tracker.record_and_check(fp) is True   # 1st
        assert tracker.record_and_check(fp) is True   # 2nd
        assert tracker.record_and_check(fp) is False  # 3rd → suppressed

    def test_different_fingerprints_not_suppressed(self):
        """Different skill bodies don't interfere."""
        tracker = ProposalTracker(suppression_threshold=3)
        fp1 = ProposalTracker.fingerprint("skill a")
        fp2 = ProposalTracker.fingerprint("skill b")
        assert tracker.record_and_check(fp1) is True
        assert tracker.record_and_check(fp1) is True
        # fp2 should not be affected by fp1's count
        assert tracker.record_and_check(fp2) is True
        assert tracker.record_and_check(fp2) is True

    def test_suppression_count(self):
        tracker = ProposalTracker(suppression_threshold=2)
        fp = ProposalTracker.fingerprint("test")
        tracker.record_and_check(fp)  # 1st
        tracker.record_and_check(fp)  # 2nd → suppressed
        assert tracker.suppression_count() == 1

    def test_reset(self):
        tracker = ProposalTracker(suppression_threshold=2)
        fp = ProposalTracker.fingerprint("test")
        tracker.record_and_check(fp)  # 1st
        assert tracker.record_and_check(fp) is False  # 2nd → suppressed
        tracker.reset()
        assert tracker.record_and_check(fp) is True   # proceeds after reset
        assert tracker.suppression_count() == 0       # counter cleared


# ── Skill domain models ──────────────────────────────────────────────────────

class TestSkillModels:
    def test_skill_review_defaults(self):
        review = SkillReview(skill_name="test")
        assert review.skill_name == "test"
        assert review.coherence == 0.0
        assert review.recommendation == "reject"
        assert review.promoted is False

    def test_skill_promotion_result_defaults(self):
        result = SkillPromotionResult(skill_name="test")
        assert result.passed is False
        assert result.verify_score == 0.0
        assert result.harness_score == 0.0


# ── Skill curator consolidation helpers ─────────────────────────────────────

class TestSkillConsolidation:
    def test_extract_keywords(self):
        keywords = _extract_keywords("this skill helps with bash shell commands")
        assert "bash" in keywords
        assert "shell" in keywords
        assert "commands" in keywords
        assert "this" not in keywords  # stopword

    def test_keyword_overlap_identical(self):
        kw = {"bash", "shell", "python"}
        assert _keyword_overlap(kw, kw) == 1.0

    def test_keyword_overlap_disjoint(self):
        assert _keyword_overlap({"bash"}, {"python"}) == 0.0

    def test_keyword_overlap_partial(self):
        overlap = _keyword_overlap({"bash", "shell"}, {"bash", "python"})
        assert overlap == 1/3  # intersection={bash}, union={bash, shell, python}

    def test_keyword_overlap_empty(self):
        assert _keyword_overlap(set(), {"a"}) == 0.0
        assert _keyword_overlap({"a"}, set()) == 0.0
