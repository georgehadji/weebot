"""A failed summary must not be passed off as one.

W2 of the V7 defect hunt. `_summarize` returned the string ``"(compression failed: {exc})"``
on an LLM error and ``"(summary unavailable)"`` on an empty completion; callers embedded it
in a summary message and dropped the turns it stood for. A failed call now returns ``""``,
and the pipeline (`context_passes.py`) turns that into an honest, labelled fallback instead
of a fake summary. H9 moved the head/tail slicing out of this class.
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
async def test_a_failed_summary_is_empty_not_an_error_string(kwargs):
    assert await _compressor(**kwargs).summarize(_conversation()) == ""


@pytest.mark.asyncio
async def test_a_successful_summary_is_returned_as_written():
    assert await _compressor(content="the middle, summarized").summarize(_conversation()) == (
        "the middle, summarized"
    )


@pytest.mark.asyncio
async def test_it_summarizes_exactly_the_messages_it_is_given():
    c = _compressor(content="ok")
    await c.summarize(_conversation(2))
    sent = c._llm.chat.call_args.kwargs["messages"][1]["content"]
    assert "turn 0" in sent and "turn 1" in sent
