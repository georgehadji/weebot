"""D5 (plan 2026-10-29): a step whose skill retrieval misses records a skill gap again.

``bdc7c74a`` moved the prompt assembly into ``_prompt_builder.py`` and dropped the call to
the gap recorder, so ``_skill_gaps`` stayed empty and the IdeaContract path in
``CompletedState`` never ran. The builder now reports the best retrieval score, and the
step setup records the gap from it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from weebot.application.agents.executor import _step_setup


class _Retriever:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores

    async def retrieve(self, query, top_k=2):
        return [
            SimpleNamespace(score=s, skill_name=f"s{i}", content_preview="", trust="trusted")
            for i, s in enumerate(self._scores)
        ]


def _executor(retriever) -> SimpleNamespace:
    return SimpleNamespace(
        _scope_tools_for=lambda step: "",
        _user_profile_cache="",
        _load_prompt=lambda: "base",
        _harness_instruction_block=None,
        _skill_prompt=None,
        _skill_retriever=retriever,
        _behavioral_learner=None,
        _state_repo=None,
        _personality=None,
        _profile_name="",
        _skills_used=[],
        _memory_snapshot=None,
        _event_bus=None,
        _current_session_id="s1",
        _skill_gaps=[],
    )


async def _build(executor) -> None:
    step = SimpleNamespace(description="deploy the docker image", context_scope=None)
    with (
        patch.object(_step_setup, "_seed_conversation", lambda *a: None),
        patch("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", True),
    ):
        await _step_setup.build_step_prompts(executor, plan=None, step=step, user_input=None)


@pytest.mark.asyncio
async def test_a_retrieval_miss_records_a_gap():
    executor = _executor(_Retriever([0.05, 0.02]))
    await _build(executor)
    assert executor._skill_gaps == [{"step": "deploy the docker image", "score": 0.05}]


@pytest.mark.asyncio
async def test_a_retrieval_hit_records_none():
    executor = _executor(_Retriever([0.9]))
    await _build(executor)
    assert executor._skill_gaps == []


@pytest.mark.asyncio
async def test_no_retriever_records_none():
    executor = _executor(None)
    await _build(executor)
    assert executor._skill_gaps == []
