"""F15: a screenshot's base64 must not be counted as text tokens.

Two call sites estimated `len(str(content)) // 4`. A list-valued message that holds a
400 KB base64 image part came out at about 100k tokens, so the compressor ran at once and
a cancelled call was billed for a prompt it never had. There is now one estimator: text
parts by length, a flat figure per image part.
"""

from __future__ import annotations

import base64
from collections import deque
from unittest.mock import AsyncMock, MagicMock

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.agents.executor._context_compressor import ContextCompressor
from weebot.application.services.context_tokenizer import ContextTokenizer
from weebot.config.constants import IMAGE_PART_TOKENS

_PNG = base64.b64encode(b"\x89PNG" * 100_000).decode()  # about 530 KB of base64


def _screenshot_message(text: str = "what is on screen?") -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG}"}},
        ],
    }


def test_an_image_part_counts_as_a_flat_figure_not_its_base64():
    tokens = ContextTokenizer().estimate_messages_tokens([_screenshot_message("x" * 400)])
    assert tokens == 100 + IMAGE_PART_TOKENS


def test_the_anthropic_image_shape_is_flat_too():
    part = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _PNG}}
    msg = {"role": "user", "content": [part]}
    assert ContextTokenizer().estimate_messages_tokens([msg]) == IMAGE_PART_TOKENS


def test_a_tool_block_without_text_is_still_counted():
    """Not an image and not a text part: counting it as zero would delay compaction."""
    block = {"type": "tool_result", "tool_use_id": "t1", "content": "y" * 4000}
    tokens = ContextTokenizer().estimate_messages_tokens([{"role": "user", "content": [block]}])
    assert tokens >= 1000


def test_plain_string_and_missing_content_are_unchanged():
    messages = [{"role": "user", "content": "a" * 40}, {"role": "assistant", "content": None}]
    assert ContextTokenizer().estimate_messages_tokens(messages) == 10


async def test_a_screenshot_does_not_trigger_compaction():
    buffer = deque([_screenshot_message() for _ in range(3)])
    compressor = ContextCompressor(buffer, context_window=128_000)
    compressor._compressor = MagicMock(compress=AsyncMock(return_value=[]))
    await compressor._maybe_compress()
    compressor._compressor.compress.assert_not_called()  # about 4.5k tokens, window 128k


async def test_a_cancelled_call_is_billed_for_the_flat_figure():
    seen = []

    async def on_done(event):
        seen.append(event.prompt_tokens)

    ex = CascadeExecutor(llm=MagicMock(), tools=MagicMock(), on_call_completed=on_done)
    await ex._call_unanswered("some/model", [_screenshot_message()])
    assert seen and seen[0] < 2 * IMAGE_PART_TOKENS
