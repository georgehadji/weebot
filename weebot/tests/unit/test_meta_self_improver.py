"""Tests for MetaSelfImprover and MetaImprovementLog."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.meta_self_improver import (
    MetaSelfImprover,
    MetaReviewResult,
)
from weebot.infrastructure.persistence.meta_improvement_log import MetaImprovementLog


class TestMetaReviewResult:
    """Tests for MetaReviewResult."""

    def test_skip_creates_inactive_result(self) -> None:
        result = MetaReviewResult.skip("feature flag disabled")
        assert result.should_apply is False
        assert result.skip_reason == "feature flag disabled"

    def test_should_apply_requires_all_conditions(self) -> None:
        # All conditions met
        result = MetaReviewResult(
            should_update_strategy=True,
            confidence=0.9,
            new_strategy="Improved strategy",
        )
        assert result.should_apply is True

    def test_should_apply_fails_on_low_confidence(self) -> None:
        result = MetaReviewResult(
            should_update_strategy=True,
            confidence=0.5,  # < 0.8
            new_strategy="Improved strategy",
        )
        assert result.should_apply is False

    def test_should_apply_fails_on_empty_strategy(self) -> None:
        result = MetaReviewResult(
            should_update_strategy=True,
            confidence=0.9,
            new_strategy="",
        )
        assert result.should_apply is False

    def test_should_apply_fails_on_false_flag(self) -> None:
        result = MetaReviewResult(
            should_update_strategy=False,
            confidence=0.9,
            new_strategy="Improved strategy",
        )
        assert result.should_apply is False


class TestMetaSelfImprover:
    """Tests for MetaSelfImprover with mocked LLM."""

    @pytest.fixture
    def mock_llm(self) -> AsyncMock:
        llm = AsyncMock()
        llm.chat = AsyncMock()
        return llm

    @pytest.fixture
    def improver(self, mock_llm: AsyncMock) -> MetaSelfImprover:
        # Use temp dir; explicitly close connections on teardown via yield
        d = tempfile.mkdtemp()
        try:
            log = MetaImprovementLog(db_path=Path(d) / "test_log.db")
            yield MetaSelfImprover(llm=mock_llm, audit_log=log)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_meta_review_disabled_by_default(self, improver: MetaSelfImprover) -> None:
        """Without the feature flag, meta-review always skips."""
        from unittest.mock import PropertyMock, patch
        with patch.object(
            MetaSelfImprover, "is_enabled",
            new_callable=PropertyMock, return_value=False,
        ):
            result = await improver.meta_review(
                target_file="test.py",
                change_summary="Test change",
            )
        assert result.should_apply is False
        assert "feature flag disabled" in result.skip_reason

    @pytest.mark.asyncio
    async def test_meta_review_handles_llm_error(
        self, improver: MetaSelfImprover, mock_llm: AsyncMock
    ) -> None:
        # Patch the property to return True so the LLM is actually called
        from unittest.mock import PropertyMock, patch
        mock_llm.chat.side_effect = RuntimeError("LLM down")

        with patch.object(
            MetaSelfImprover, "is_enabled",
            new_callable=PropertyMock, return_value=True,
        ):
            result = await improver.meta_review(
                target_file="test.py",
                change_summary="Test change",
            )
        assert result.should_apply is False
        assert "LLM error" in result.skip_reason


class TestMetaImprovementLog:
    """Tests for the append-only audit log."""

    @pytest.fixture
    def temp_db(self) -> Path:
        d = tempfile.mkdtemp()
        path = Path(d) / "test_meta.db"
        yield path
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    @pytest.fixture
    def log(self, temp_db: Path) -> MetaImprovementLog:
        return MetaImprovementLog(db_path=temp_db)

    @pytest.mark.asyncio
    async def test_record_and_retrieve(self, log: MetaImprovementLog) -> None:
        edit_id = await log.record(
            editor="MetaSelfImprover",
            target_file="self_improver.py",
            change_summary="Added prompt variants to allowlist",
            previous_hash="abc",
            new_hash="def",
        )
        assert edit_id

        recent = await log.get_recent(limit=5)
        assert len(recent) == 1
        assert recent[0]["editor"] == "MetaSelfImprover"
        assert "prompt variants" in recent[0]["change_summary"]
