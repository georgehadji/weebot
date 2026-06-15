"""Phase 2 unit tests — retrieval-miss skill-gap detection."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ── _maybe_record_skill_gap ────────────────────────────────────────────────────


class TestMaybeRecordSkillGap:
    def _executor_stub(self):
        e = MagicMock()
        e._skill_gaps = []
        return e

    def test_flag_off_no_gap_recorded(self):
        from weebot.application.agents.executor._base import _maybe_record_skill_gap

        executor = self._executor_stub()
        with patch("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", False):
            _maybe_record_skill_gap(executor, "some step", 0.10)

        assert executor._skill_gaps == []

    def test_score_above_threshold_no_gap(self):
        from weebot.application.agents.executor._base import _maybe_record_skill_gap

        executor = self._executor_stub()
        with (
            patch("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", True),
            patch("weebot.config.learning.TAU_CREATE", 0.35),
        ):
            _maybe_record_skill_gap(executor, "some step", 0.50)

        assert executor._skill_gaps == []

    def test_score_below_threshold_gap_recorded(self):
        from weebot.application.agents.executor._base import _maybe_record_skill_gap

        executor = self._executor_stub()
        with (
            patch("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", True),
            patch("weebot.config.learning.TAU_CREATE", 0.35),
        ):
            _maybe_record_skill_gap(executor, "deploy docker image", 0.10)

        assert len(executor._skill_gaps) == 1
        gap = executor._skill_gaps[0]
        assert gap["score"] == pytest.approx(0.10)
        assert "deploy docker image" in gap["step"]

    def test_score_exactly_at_threshold_no_gap(self):
        from weebot.application.agents.executor._base import _maybe_record_skill_gap

        executor = self._executor_stub()
        with (
            patch("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", True),
            patch("weebot.config.learning.TAU_CREATE", 0.35),
        ):
            # score == TAU_CREATE is a hit, not a miss
            _maybe_record_skill_gap(executor, "some step", 0.35)

        assert executor._skill_gaps == []

    def test_step_truncated_to_200_chars(self):
        from weebot.application.agents.executor._base import _maybe_record_skill_gap

        executor = self._executor_stub()
        long_step = "x" * 300
        with (
            patch("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", True),
            patch("weebot.config.learning.TAU_CREATE", 0.35),
        ):
            _maybe_record_skill_gap(executor, long_step, 0.05)

        assert len(executor._skill_gaps[0]["step"]) <= 200

    def test_multiple_gaps_accumulated(self):
        from weebot.application.agents.executor._base import _maybe_record_skill_gap

        executor = self._executor_stub()
        with (
            patch("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", True),
            patch("weebot.config.learning.TAU_CREATE", 0.35),
        ):
            _maybe_record_skill_gap(executor, "step one", 0.10)
            _maybe_record_skill_gap(executor, "step two", 0.20)

        assert len(executor._skill_gaps) == 2


# ── ExecutorAgent._skill_gaps initialised empty ───────────────────────────────


class TestExecutorSkillGaps:
    def test_skill_gaps_initialised(self):
        from weebot.application.agents.executor._base import ExecutorAgent
        from weebot.application.models.tool_collection import ToolCollection

        llm = MagicMock()
        tools = MagicMock(spec=ToolCollection)
        executor = ExecutorAgent(llm=llm, tools=tools)

        assert hasattr(executor, "_skill_gaps")
        assert executor._skill_gaps == []


# ── SkillGapDetected event ────────────────────────────────────────────────────


class TestSkillGapDetectedEvent:
    def test_fields(self):
        from weebot.domain.models.event import SkillGapDetected

        ev = SkillGapDetected(
            session_id="s1",
            step_description="deploy docker container",
            best_score=0.12,
        )
        assert ev.type == "skill_gap_detected"
        assert ev.session_id == "s1"
        assert ev.best_score == pytest.approx(0.12)

    def test_id_auto_generated(self):
        from weebot.domain.models.event import SkillGapDetected

        e1 = SkillGapDetected(session_id="s", step_description="step")
        e2 = SkillGapDetected(session_id="s", step_description="step")
        assert e1.id != e2.id
