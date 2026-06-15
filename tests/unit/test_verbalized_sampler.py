"""Tests for Verbalized Sampling Phase 0 — foundation models + sampler.

Covers:
1. SampledResponse probability coercion (string, percent, float)
2. SampledDistribution mode, tail, weighted_sample, texts
3. parse_sampled_distribution — clean JSON, fenced JSON, trailing prose, malformed
4. VerbalizedSampler fail-open on LLM error / timeout
5. Prompt build with k, threshold, cot variant injection
"""
from __future__ import annotations

import json
import random
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.models.structured_output import (
    SampledDistribution,
    SampledResponse,
    parse_sampled_distribution,
)


# ============================================================================
# 1. SampledResponse — probability coercion
# ============================================================================

class TestSampledResponseCoercion:
    """SampledResponse probability field accepts diverse formats."""

    def test_float_probability(self):
        """Float probability passes through."""
        r = SampledResponse(text="a", probability=0.5)
        assert r.probability == 0.5

    def test_string_probability(self):
        """String probability like '0.5' is coerced to float."""
        r = SampledResponse(text="a", probability="0.5")
        assert r.probability == 0.5

    def test_percent_probability(self):
        """String percent like '12%' is coerced to 0.12."""
        r = SampledResponse(text="b", probability="12%")
        assert r.probability == 0.12

    def test_percent_100(self):
        """100% coerces to 1.0."""
        r = SampledResponse(text="c", probability="100%")
        assert r.probability == 1.0

    def test_lower_bound_zero(self):
        """probability=0.0 is valid."""
        r = SampledResponse(text="a", probability=0.0)
        assert r.probability == 0.0

    def test_upper_bound_one(self):
        """probability=1.0 is valid."""
        r = SampledResponse(text="a", probability=1.0)
        assert r.probability == 1.0


# ============================================================================
# 2. SampledDistribution — selection
# ============================================================================

class TestSampledDistribution:
    """SampledDistribution selection methods."""

    def test_mode_returns_highest_probability(self):
        """mode() returns the argmax response."""
        d = SampledDistribution(responses=[
            SampledResponse(text="a", probability=0.2),
            SampledResponse(text="b", probability=0.7),
            SampledResponse(text="c", probability=0.1),
        ])
        assert d.mode().text == "b"
        assert d.mode().probability == 0.7

    def test_mode_empty_returns_none(self):
        """mode() returns None when empty."""
        d = SampledDistribution()
        assert d.mode() is None

    def test_tail_filters_below_threshold(self):
        """tail(0.3) returns responses with prob < 0.3."""
        d = SampledDistribution(responses=[
            SampledResponse(text="a", probability=0.2),
            SampledResponse(text="b", probability=0.7),
            SampledResponse(text="c", probability=0.1),
        ])
        tail = d.tail(0.3)
        assert len(tail) == 2
        assert tail[0].text == "a"
        assert tail[1].text == "c"

    def test_tail_empty_when_all_above_threshold(self):
        """tail returns empty list when all probabilities are above threshold."""
        d = SampledDistribution(responses=[
            SampledResponse(text="a", probability=0.5),
            SampledResponse(text="b", probability=0.5),
        ])
        assert d.tail(0.4) == []

    def test_weighted_sample_deterministic(self):
        """weighted_sample with seeded RNG is deterministic."""
        d = SampledDistribution(responses=[
            SampledResponse(text="a", probability=0.8),
            SampledResponse(text="b", probability=0.2),
        ])
        rng = random.Random(42)
        result = d.weighted_sample(rng=rng)
        assert result is not None
        assert result.text in ("a", "b")

    def test_weighted_sample_empty(self):
        """weighted_sample returns None when empty."""
        d = SampledDistribution()
        assert d.weighted_sample() is None

    def test_texts_returns_all_texts(self):
        """texts() returns all response texts in order."""
        d = SampledDistribution(responses=[
            SampledResponse(text="first", probability=0.5),
            SampledResponse(text="second", probability=0.5),
        ])
        assert d.texts() == ["first", "second"]

    def test_bool_true_when_nonempty(self):
        """SampledDistribution is truthy when it has responses."""
        d = SampledDistribution(responses=[SampledResponse(text="a", probability=1.0)])
        assert bool(d) is True

    def test_bool_false_when_empty(self):
        """SampledDistribution is falsy when empty."""
        d = SampledDistribution()
        assert bool(d) is False


# ============================================================================
# 3. parse_sampled_distribution — parsing
# ============================================================================

class TestParseSampledDistribution:
    """Parses LLM responses into SampledDistribution."""

    def test_clean_json(self):
        """Valid JSON object is parsed correctly."""
        raw = '{"responses": [{"text": "a", "probability": 0.5}]}'
        d = parse_sampled_distribution(raw)
        assert len(d.responses) == 1
        assert d.responses[0].text == "a"

    def test_fenced_json(self):
        """Markdown-fenced ```json ... ``` is parsed."""
        raw = '```json\n{"responses": [{"text": "b", "probability": 0.7}]}\n```'
        d = parse_sampled_distribution(raw)
        assert len(d.responses) == 1
        assert d.responses[0].text == "b"

    def test_trailing_prose(self):
        """JSON followed by explanatory prose is parsed (extracts JSON)."""
        raw = '{"responses": [{"text": "c", "probability": 0.3}]}\\n\\nExplanation: this is the best approach.'
        d = parse_sampled_distribution(raw)
        assert len(d.responses) == 1
        assert d.responses[0].text == "c"

    def test_malformed_json_returns_empty(self):
        """Invalid JSON returns empty distribution (fail-open)."""
        d = parse_sampled_distribution("not json at all")
        assert len(d.responses) == 0

    def test_empty_string_returns_empty(self):
        """Empty/whitespace input returns empty distribution."""
        assert len(parse_sampled_distribution("").responses) == 0
        assert len(parse_sampled_distribution("   ").responses) == 0

    def test_missing_responses_key_returns_empty(self):
        """Valid JSON but missing 'responses' key returns empty."""
        d = parse_sampled_distribution('{"answer": 42}')
        assert len(d.responses) == 0

    def test_none_returns_empty(self):
        """None input returns empty distribution."""
        d = parse_sampled_distribution(None)  # type: ignore
        assert len(d.responses) == 0

    def test_complex_distribution(self):
        """Multi-candidate distribution with different formats parses."""
        raw = json.dumps({
            "responses": [
                {"text": "Use pytest", "probability": 0.6},
                {"text": "Use unittest", "probability": 0.3},
                {"text": "Write custom runner", "probability": 0.1},
            ]
        })
        d = parse_sampled_distribution(raw)
        assert len(d.responses) == 3
        assert d.mode().text == "Use pytest"


# ============================================================================
# 4. VerbalizedSampler — fail-open
# ============================================================================

class TestVerbalizedSamplerFailOpen:
    """VerbalizedSampler falls back to single-item distribution on errors."""

    @pytest.mark.asyncio
    async def test_fail_open_on_llm_exception(self):
        """LLM raising an exception returns single-item fallback."""
        from weebot.application.services.verbalized_sampler import (
            VerbalizedSampler,
        )

        llm = AsyncMock()
        llm.chat.side_effect = RuntimeError("LLM unavailable")

        sampler = VerbalizedSampler(llm, model="test-model")
        dist = await sampler.sample("test instruction")
        assert len(dist.responses) == 1
        # Fallback text is the instruction itself
        assert dist.responses[0].text == "test instruction"
        assert dist.responses[0].probability == 1.0

    @pytest.mark.asyncio
    async def test_fail_open_on_timeout(self):
        """LLM timeout returns single-item fallback."""
        from weebot.application.services.verbalized_sampler import (
            VerbalizedSampler,
        )

        llm = AsyncMock()
        llm.chat.side_effect = asyncio.TimeoutError()

        sampler = VerbalizedSampler(llm, model="test-model")
        dist = await sampler.sample("timeout test", timeout=0.1)
        assert len(dist.responses) == 1

    @pytest.mark.asyncio
    async def test_fail_open_empty_parse(self):
        """LLM returning unparseable text returns single-item fallback."""
        from weebot.application.services.verbalized_sampler import (
            VerbalizedSampler,
        )

        llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "I don't know how to do this"
        llm.chat.return_value = mock_response

        sampler = VerbalizedSampler(llm, model="test-model")
        dist = await sampler.sample("fallback test")
        # Returns single-item fallback since the response was unparseable
        assert len(dist.responses) == 1
        assert dist.responses[0].text == "fallback test"


# ============================================================================
# 5. Prompt build
# ============================================================================

class TestVerbalizedSamplerPrompt:
    """Sampler builds the correct prompt based on parameters."""

    @pytest.mark.asyncio
    async def test_standard_variant(self):
        """Standard variant uses direct instruction prompt."""
        from weebot.application.services.verbalized_sampler import (
            VerbalizedSampler,
        )

        llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"responses": [{"text": "a", "probability": 1.0}]}'
        llm.chat.return_value = mock_response

        sampler = VerbalizedSampler(llm, model="test-model")
        await sampler.sample("do something", k=5)

        # Verify the LLM was called
        assert llm.chat.called
        call_args = llm.chat.call_args[1]
        assert call_args.get("response_format") == {"type": "json_object"}
        assert call_args.get("temperature") is not None

    @pytest.mark.asyncio
    async def test_cot_variant_adds_reasoning_instruction(self):
        """Cot variant includes 'reason step-by-step' in system prompt."""
        from weebot.application.services.verbalized_sampler import (
            VerbalizedSampler,
        )

        llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"responses": [{"text": "candidate", "probability": 1.0}]}'
        llm.chat.return_value = mock_response

        sampler = VerbalizedSampler(llm, model="test-model")
        await sampler.sample("think about this", k=3, variant="cot")

        call_args = llm.chat.call_args[1]
        messages = call_args.get("messages", [])
        system_msg = messages[0]["content"] if messages else ""
        # Cot variant should include reasoning instruction
        assert "reason step-by-step" in system_msg.lower()

    @pytest.mark.asyncio
    async def test_context_is_prepended(self):
        """Context string is prepended to the instruction."""
        from weebot.application.services.verbalized_sampler import (
            VerbalizedSampler,
        )

        llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"responses": [{"text": "a", "probability": 1.0}]}'
        llm.chat.return_value = mock_response

        sampler = VerbalizedSampler(llm, model="test-model")
        await sampler.sample(
            "fix the bug",
            context="The user reported a login crash.",
        )

        call_args = llm.chat.call_args[1]
        messages = call_args.get("messages", [])
        user_msg = messages[-1]["content"] if messages else ""
        assert "login crash" in user_msg
        assert "fix the bug" in user_msg


# ============================================================================
# 6. Constants
# ============================================================================

class TestVSConstants:
    """VS config constants have correct types and defaults."""

    def test_default_k(self):
        from weebot.config.constants import VS_DEFAULT_K
        assert VS_DEFAULT_K == 5

    def test_tail_threshold(self):
        from weebot.config.constants import VS_TAIL_THRESHOLD
        assert VS_TAIL_THRESHOLD == 0.10

    def test_flags_default_off(self):
        from weebot.config.constants import (
            VS_ENABLE_RECOVERY,
            VS_ENABLE_PLANNING,
            VS_ENABLE_DREAMER,
            VS_ENABLE_OPTIMIZER,
            VS_ENABLE_CONTENT,
        )
        assert VS_ENABLE_RECOVERY is False
        assert VS_ENABLE_PLANNING is False
        assert VS_ENABLE_DREAMER is False
        assert VS_ENABLE_OPTIMIZER is False
        assert VS_ENABLE_CONTENT is False

    def test_vs_model_refs(self):
        from weebot.config.model_refs import get_vs_model, MODEL_VS_CAPABLE
        model = get_vs_model()
        assert model == MODEL_VS_CAPABLE
        assert model == "qwen/qwen3.7-max"
