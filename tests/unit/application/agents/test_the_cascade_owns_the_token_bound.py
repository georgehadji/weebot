"""E1: the cascade passes the completion bound its adapter would have chosen.

The cascade decided *which* model to call but not *how long* the answer could be: both
`self._llm.chat(...)` sites passed no `max_tokens`, so the bound was whatever the adapter
hard-coded -- 16384 in `openai_adapter.py`, 4096 in `anthropic_adapter.py`. Two numbers,
two files, no name.

`config/token_bounds.py` names both and resolves the right one from the adapter. These
tests hold the resolution total: a known adapter yields its own number (so passing it
changes nothing), an unknown one yields `None` (so passing it still changes nothing), and
the cascade really hands that value to `chat`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.config.token_bounds import COMPLETION_TOKENS_BY_ADAPTER, completion_bound
from weebot.domain.models.llm_response import LLMResponse


# The resolution is by class NAME, so the doubles carry the real names. The real
# adapters are covered by 	est_the_values_are_the_ones_the_adapters_hard_code, which
# reads their source: what is being tested here is the matching, not the numbers.
_AnthropicAdapter = type("AnthropicAdapter", (), {})
_OpenAIAdapter = type("OpenAIAdapter", (), {})
_UnknownAdapter = type("SomeOtherAdapter", (), {})


class _Tools:
    """The call site asks the collection for its schema before calling the model."""

    def to_params(self) -> list:
        return []


class _RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)

        async def _result() -> LLMResponse:
            return LLMResponse(content="ok", tool_calls=[])

        return _result()


class TestTheTableNamesTheAdaptersOwnNumbers:
    def test_the_values_are_the_ones_the_adapters_hard_code(self):
        """If an adapter's default moves, this is where the two are reconciled."""
        import pathlib

        openai = pathlib.Path("weebot/infrastructure/adapters/llm/openai_adapter.py").read_text(
            encoding="utf-8"
        )
        anthropic = pathlib.Path(
            "weebot/infrastructure/adapters/llm/anthropic_adapter.py"
        ).read_text(encoding="utf-8")
        assert f'kwargs["max_tokens"] = {COMPLETION_TOKENS_BY_ADAPTER["openaiadapter"]}' in openai
        assert f"max_tokens or {COMPLETION_TOKENS_BY_ADAPTER['anthropicadapter']}" in anthropic

    def test_an_anthropic_adapter_resolves_to_its_own_bound(self):
        assert completion_bound(_AnthropicAdapter()) == 4096

    def test_an_openai_adapter_resolves_to_its_own_bound(self):
        assert completion_bound(_OpenAIAdapter()) == 16384

    def test_an_unknown_adapter_resolves_to_none(self):
        """`None` means "pass nothing", which is exactly today's behaviour."""
        assert completion_bound(_UnknownAdapter()) is None

    def test_no_adapter_is_none(self):
        assert completion_bound(None) is None


class TestTheCascadePassesIt:
    def _executor(self, llm) -> CascadeExecutor:
        return CascadeExecutor(llm=llm, tools=_Tools(), agent_role="executor")

    def test_the_bound_is_resolved_once_at_construction(self):
        assert self._executor(_AnthropicAdapter())._completion_bound == 4096
        assert self._executor(_UnknownAdapter())._completion_bound is None

    def test_a_known_adapter_is_passed_explicitly(self):
        """The call site, not just the property: an unused bound would pass the first four."""

        llm = _RecordingLLM()
        executor = self._executor(_AnthropicAdapter())
        executor._llm = llm  # the recording double, but the bound from the real adapter
        asyncio.run(
            executor._cascade_try_chat(
                messages=[{"role": "user", "content": "hi"}],
                model_id="anthropic/claude-3.5-sonnet",
                timeout=5.0,
            )
        )
        assert llm.calls, "the call site did not reach the adapter"
        assert llm.calls[0]["max_tokens"] == 4096

    def test_an_unknown_adapter_is_passed_none(self):
        llm = _RecordingLLM()
        executor = self._executor(_UnknownAdapter())
        executor._llm = llm
        asyncio.run(
            executor._cascade_try_chat(
                messages=[{"role": "user", "content": "hi"}],
                model_id="some/model",
                timeout=5.0,
            )
        )
        assert llm.calls and llm.calls[0]["max_tokens"] is None
