"""A failed summary must not cost the caller its conversation.

W2 of the V7 defect hunt. `_summarize` returned the string
``"(compression failed: {exc})"`` on an LLM error and ``"(summary
unavailable)"`` on an empty completion. Both callers embedded that string in a
summary message and dropped the middle turns it stood for, returning a
normally-shaped result the caller could not tell from a successful
compression -- so it committed the replacement and those turns were gone.

Compression is lossy by design, which is exactly why its failure has to be a
no-op rather than a loss. Both call sites now match the behaviour already
documented for a buffer too short to compress: return the input unchanged.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.conversation_compressor import ConversationCompressor
from weebot.domain.models.llm_response import LLMResponse


def _compressor(*, content=None, error=None):
    llm = MagicMock()
    if error is not None:
        llm.chat = AsyncMock(side_effect=error)
    else:
        llm.chat = AsyncMock(return_value=LLMResponse(content=content))
    return ConversationCompressor(llm=llm, cheap_model="test-model")


def _conversation(n=12):
    return [{"role": "user", "content": f"turn {i} carries detail {i}"} for i in range(n)]


class TestFailedCompressionIsANoOp:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"error": RuntimeError("provider 503")},
            {"content": ""},
            {"content": None},
            {"content": "   "},
        ],
        ids=["llm_raises", "empty_content", "none_content", "whitespace_only"],
    )
    async def test_no_turn_is_lost(self, kwargs):
        convo = _conversation()

        result = await _compressor(**kwargs).compress(list(convo))

        surviving = {m.get("content", "") for m in result}
        lost = [m["content"] for m in convo if m["content"] not in surviving]
        assert lost == [], f"{len(lost)} turn(s) discarded by a failed compression"

    @pytest.mark.asyncio
    async def test_no_error_string_is_passed_off_as_a_summary(self):
        result = await _compressor(error=RuntimeError("provider 503")).compress(_conversation())

        blob = " ".join(str(m.get("content", "")) for m in result)
        assert "compression failed" not in blob
        assert "summary unavailable" not in blob
        assert "Context summary" not in blob


class TestSuccessfulCompressionStillCompresses:
    """No-regression: the fix must not disable compression."""

    @pytest.mark.asyncio
    async def test_middle_is_replaced_by_the_summary(self):
        convo = _conversation()

        result = await _compressor(content="the middle, summarized").compress(list(convo))

        assert len(result) < len(convo)
        blob = " ".join(str(m.get("content", "")) for m in result)
        assert "the middle, summarized" in blob
        assert "Context summary" in blob

    @pytest.mark.asyncio
    async def test_short_buffer_is_returned_unchanged(self):
        convo = _conversation(2)

        result = await _compressor(content="unused").compress(list(convo))

        assert result == convo


class TestTrajectoryExporterSharesTheContract:
    """trajectory_exporter.py calls _summarize directly and dropped events the
    same way. The empty-summary contract has to hold at both call sites."""

    @pytest.mark.asyncio
    async def test_summarize_returns_empty_string_on_failure(self):
        assert await _compressor(error=RuntimeError("boom"))._summarize(_conversation()) == ""

    @pytest.mark.asyncio
    async def test_summarize_returns_empty_string_on_empty_completion(self):
        assert await _compressor(content="")._summarize(_conversation()) == ""

    @pytest.mark.asyncio
    async def test_summarize_returns_the_summary_on_success(self):
        assert await _compressor(content="a summary")._summarize(_conversation()) == "a summary"
