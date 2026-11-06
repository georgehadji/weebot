"""Compression v2: pure passes first, one model call last, pairs never split (H9)."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock

import pytest

from weebot.application.agents.executor._context_compressor import (
    ContextCompressor,
    catalog_window,
)
from weebot.application.agents.executor._tool_pairing import sanitize_tool_call_pairing
from weebot.application.services.context_passes import (
    DedupeResults,
    DeterministicFallback,
    PruneOldToolOutputs,
    TokenBudget,
    compress_messages,
    default_passes,
    select_tail,
)
from weebot.application.services.context_tokenizer import ContextTokenizer

_tokens = ContextTokenizer().estimate_messages_tokens


def _tool_heavy(n=40, chars=20_000):
    """A task message, then n (assistant call, tool result) pairs of about 5K tokens each."""
    msgs = [{"role": "user", "content": "do the task"}]
    for i in range(n):
        call = {"id": f"c{i}", "function": {"name": f"tool_{i % 3}", "arguments": "{}"}}
        msgs.append({"role": "assistant", "content": "", "tool_calls": [call]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"{i}:" + "x" * chars})
    return msgs


def _prose_heavy():
    """Short tool results plus one huge user message: pruning cannot reach the target."""
    msgs = _tool_heavy(chars=80)
    msgs.append({"role": "user", "content": "z " * 60_000})
    return msgs + [{"role": "assistant", "content": "ok"}] * 4


def _no_llm():
    return AsyncMock(side_effect=AssertionError("the pure passes should have been enough"))


@pytest.mark.asyncio
async def test_a_tool_heavy_buffer_falls_below_target_without_a_model_call():
    msgs, budget, summarize = _tool_heavy(), TokenBudget(128_000), _no_llm()
    assert _tokens(msgs) > budget.trigger_tokens

    out = await compress_messages(msgs, budget, default_passes(summarize))

    assert _tokens(out) <= budget.target_tokens
    summarize.assert_not_called()


@pytest.mark.asyncio
async def test_the_head_and_the_protected_tail_survive_verbatim():
    msgs = _tool_heavy()
    out = await compress_messages(msgs, TokenBudget(128_000), default_passes(_no_llm()))
    assert out[:3] == msgs[:3] and out[-4:] == msgs[-4:]


@pytest.mark.asyncio
async def test_a_tool_call_is_never_separated_from_its_result():
    for summarize in (_no_llm(), AsyncMock(return_value="sum"), AsyncMock(return_value="")):
        out = await compress_messages(
            _prose_heavy(), TokenBudget(50_000), default_passes(summarize)
        )
        assert sanitize_tool_call_pairing(out) == out


def test_the_tail_never_starts_on_a_tool_result():
    msgs = _tool_heavy(n=10, chars=400)
    for target in range(1, 600, 37):
        start = select_tail(msgs, target)
        assert start == len(msgs) or msgs[start]["role"] != "tool"


def test_the_last_messages_are_protected_whatever_the_target():
    assert select_tail(_tool_heavy(n=10, chars=400), target_tokens=1, protect_last_n=4) <= 17


@pytest.mark.asyncio
async def test_a_pruned_result_names_its_tool_and_keeps_the_spill_path():
    footer = "[full output: /spill/s/c1.txt, 9000 chars, read with file_editor]"
    spilled = f"head\n{footer}\n" + "y" * 300
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "shell"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": spilled},
    ]
    out = await PruneOldToolOutputs().apply(msgs, TokenBudget(1000))
    assert out[1]["content"].startswith("[tool output pruned: shell, ")
    assert "spill: /spill/s/c1.txt" in out[1]["content"]
    assert out[0] == msgs[0]


@pytest.mark.asyncio
async def test_short_results_are_not_pruned():
    msgs = [{"role": "tool", "tool_call_id": "c", "content": "ok"}]
    assert await PruneOldToolOutputs().apply(msgs, TokenBudget(1000)) == msgs


@pytest.mark.asyncio
async def test_only_the_last_copy_of_an_identical_result_is_kept():
    same = "same output " * 40
    msgs = [{"role": "tool", "tool_call_id": str(i), "content": same} for i in range(3)]
    out = await DedupeResults().apply(msgs, TokenBudget(1000))
    assert [m["content"] == same for m in out] == [False, False, True]


@pytest.mark.asyncio
async def test_the_summary_is_a_user_message_not_a_system_one():
    summarize = AsyncMock(return_value="what happened")
    out = await compress_messages(_prose_heavy(), TokenBudget(50_000), default_passes(summarize))

    summary = [m for m in out if "Context summary" in str(m.get("content"))]
    assert len(summary) == 1 and summary[0]["role"] == "user"
    assert "what happened" in summary[0]["content"]
    assert not any(m["role"] == "system" for m in out)


@pytest.mark.asyncio
async def test_a_failed_summary_falls_back_to_a_labelled_drop_naming_the_tools():
    out = await compress_messages(
        _prose_heavy(), TokenBudget(50_000), default_passes(AsyncMock(return_value=""))
    )

    dropped = [m for m in out if "not summarized" in str(m.get("content"))]
    assert len(dropped) == 1 and dropped[0]["role"] == "user"
    assert "tool_0" in dropped[0]["content"]
    assert "compression failed" not in str(out)


@pytest.mark.asyncio
async def test_the_fallback_leaves_a_real_summary_alone():
    summary = [{"role": "user", "content": "[Context summary — 3 turns compressed]\nfacts"}]
    assert await DeterministicFallback().apply(summary, TokenBudget(1000)) == summary


@pytest.mark.asyncio
async def test_a_raising_pass_costs_the_caller_nothing():
    class Boom:
        name = "boom"

        async def apply(self, middle, budget):
            raise RuntimeError("bug")

    msgs = _tool_heavy()
    assert await compress_messages(msgs, TokenBudget(128_000), (Boom(),)) == msgs


@pytest.mark.asyncio
async def test_a_buffer_under_target_is_returned_unchanged():
    msgs = _tool_heavy(n=3, chars=100)
    assert await compress_messages(msgs, TokenBudget(128_000), default_passes(_no_llm())) == msgs


# ── window and trigger ──────────────────────────────────────────────────────


def test_the_trigger_is_75_percent_under_512k_and_50_percent_above():
    assert TokenBudget(128_000).trigger_tokens == 96_000
    assert TokenBudget(1_000_000).trigger_tokens == 500_000


def test_the_window_comes_from_the_catalog_and_falls_back_for_an_unknown_model():
    from weebot.config.model_catalog import MODELS

    model_id, cfg = next(iter(MODELS.items()))
    assert catalog_window(model_id, 1) == cfg.context_window
    assert catalog_window("no/such-model", 4242) == 4242
    assert catalog_window(None, 4242) == 4242


def _compressor(buf, window):
    c = ContextCompressor(buf, context_window=window, window_for=lambda model, default: default)
    c._compressor = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_a_one_million_token_window_does_not_compress_at_100k_tokens():
    buf = deque(_tool_heavy(n=20, chars=20_000))
    assert 90_000 < _tokens(list(buf)) < 130_000
    snapshot = list(buf)

    await _compressor(buf, 1_000_000)._maybe_compress()

    assert list(buf) == snapshot


@pytest.mark.asyncio
async def test_the_same_buffer_compresses_under_a_128k_window():
    buf = deque(_tool_heavy(n=40, chars=20_000))
    c = _compressor(buf, 128_000)

    await c._maybe_compress()

    assert _tokens(list(buf)) <= TokenBudget(128_000).target_tokens
    c._compressor.summarize.assert_not_called()


@pytest.mark.asyncio
async def test_the_window_follows_the_model_that_answered():
    c = ContextCompressor(
        deque(), context_window=128_000, window_for=lambda m, d: 7 if m == "m" else d
    )
    assert c.window() == 128_000
    await c.track_usage_and_maybe_compress(type("R", (), {"model": "m", "usage": {}})())
    assert c.window() == 7


@pytest.mark.asyncio
async def test_force_compress_shrinks_a_buffer_that_is_under_the_trigger():
    buf = deque(_tool_heavy(n=12, chars=20_000))  # about 60K tokens, under the 96K trigger
    before = _tokens(list(buf))

    assert await _compressor(buf, 128_000).force_compress(ratio=0.5) is True
    assert _tokens(list(buf)) < before
