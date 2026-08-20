"""Tests for context-scoped executor prompt assembly (ICM Phase A/B).

Covers: Step.context_scope roundtrip, and build_executor_prompt honoring
scope by including/excluding sources per the _SCOPE_SOURCES table.
"""

from __future__ import annotations

import pytest

from weebot.application.agents.executor._prompt_builder import build_executor_prompt
from weebot.domain.models.plan import ContextScope, Step


class _FakePersonality:
    loaded = True

    def get_system_prompt(self, profile_name: str = "") -> str:
        return "PERSONALITY_MARKER_TEXT"


class _FakeStateRepo:
    async def get_memory_entry(self, key: str) -> dict:
        return {"entry_text": "USER_PROFILE_MARKER_TEXT"}


class _FakeBehavioralLearner:
    def get_rules_for_prompt(self) -> str:
        return "# Behavioral Rules\n- BEHAVIORAL_RULE_MARKER_TEXT"


class _FakeSkillMatch:
    def __init__(self, skill_name: str, score: float, content_preview: str):
        self.skill_name = skill_name
        self.score = score
        self.content_preview = content_preview


class _FakeSkillRetriever:
    async def retrieve(self, step_description: str, top_k: int = 2):
        return [_FakeSkillMatch("test-skill", 0.9, "SKILL_CONTENT_MARKER_TEXT")]


@pytest.mark.asyncio
async def test_step_model_accepts_context_scope_roundtrip():
    step = Step(id="s1", description="do thing", context_scope=ContextScope.MINIMAL)
    dumped = step.model_dump()
    assert dumped["context_scope"] == "minimal"
    restored = Step.model_validate(dumped)
    assert restored.context_scope == ContextScope.MINIMAL


def test_step_default_context_scope_is_full():
    step = Step(id="s1", description="do thing")
    assert step.context_scope == ContextScope.FULL


@pytest.mark.asyncio
async def test_minimal_scope_excludes_profile_personality_skills_behavioral():
    prompt = await build_executor_prompt(
        "run a shell command",
        base_prompt="BASE_PROMPT_MARKER",
        context_scope="minimal",
        harness_block="HARNESS_MARKER",
        skill_prompt="INJECTED_SKILL_MARKER",
        skill_retriever=_FakeSkillRetriever(),
        behavioral_learner=_FakeBehavioralLearner(),
        state_repo=_FakeStateRepo(),
        personality=_FakePersonality(),
        profile_name="default",
    )
    assert "BASE_PROMPT_MARKER" in prompt
    assert "HARNESS_MARKER" in prompt
    assert "USER_PROFILE_MARKER_TEXT" not in prompt
    assert "PERSONALITY_MARKER_TEXT" not in prompt
    assert "INJECTED_SKILL_MARKER" not in prompt
    assert "SKILL_CONTENT_MARKER_TEXT" not in prompt
    assert "BEHAVIORAL_RULE_MARKER_TEXT" not in prompt


@pytest.mark.asyncio
async def test_skill_scope_includes_skills_and_behavioral_excludes_profile_personality():
    prompt = await build_executor_prompt(
        "implement a function",
        base_prompt="BASE_PROMPT_MARKER",
        context_scope="skill",
        harness_block="HARNESS_MARKER",
        skill_prompt="INJECTED_SKILL_MARKER",
        skill_retriever=_FakeSkillRetriever(),
        behavioral_learner=_FakeBehavioralLearner(),
        state_repo=_FakeStateRepo(),
        personality=_FakePersonality(),
        profile_name="default",
    )
    assert "INJECTED_SKILL_MARKER" in prompt
    assert "SKILL_CONTENT_MARKER_TEXT" in prompt
    assert "BEHAVIORAL_RULE_MARKER_TEXT" in prompt
    assert "USER_PROFILE_MARKER_TEXT" not in prompt
    assert "PERSONALITY_MARKER_TEXT" not in prompt


@pytest.mark.asyncio
async def test_creative_scope_includes_everything():
    prompt = await build_executor_prompt(
        "write user-facing copy",
        base_prompt="BASE_PROMPT_MARKER",
        context_scope="creative",
        harness_block="HARNESS_MARKER",
        skill_prompt="INJECTED_SKILL_MARKER",
        skill_retriever=_FakeSkillRetriever(),
        behavioral_learner=_FakeBehavioralLearner(),
        state_repo=_FakeStateRepo(),
        personality=_FakePersonality(),
        profile_name="default",
    )
    assert "INJECTED_SKILL_MARKER" in prompt
    assert "SKILL_CONTENT_MARKER_TEXT" in prompt
    assert "BEHAVIORAL_RULE_MARKER_TEXT" in prompt
    assert "USER_PROFILE_MARKER_TEXT" in prompt
    assert "PERSONALITY_MARKER_TEXT" in prompt


@pytest.mark.asyncio
async def test_full_scope_backward_compat_includes_everything():
    prompt = await build_executor_prompt(
        "anything",
        base_prompt="BASE_PROMPT_MARKER",
        context_scope="full",
        harness_block="HARNESS_MARKER",
        skill_prompt="INJECTED_SKILL_MARKER",
        skill_retriever=_FakeSkillRetriever(),
        behavioral_learner=_FakeBehavioralLearner(),
        state_repo=_FakeStateRepo(),
        personality=_FakePersonality(),
        profile_name="default",
    )
    for marker in (
        "BASE_PROMPT_MARKER",
        "HARNESS_MARKER",
        "INJECTED_SKILL_MARKER",
        "SKILL_CONTENT_MARKER_TEXT",
        "BEHAVIORAL_RULE_MARKER_TEXT",
        "USER_PROFILE_MARKER_TEXT",
        "PERSONALITY_MARKER_TEXT",
    ):
        assert marker in prompt


@pytest.mark.asyncio
async def test_default_scope_omitted_falls_back_to_full():
    prompt = await build_executor_prompt(
        "anything",
        base_prompt="BASE_PROMPT_MARKER",
        harness_block="HARNESS_MARKER",
        personality=_FakePersonality(),
        profile_name="default",
    )
    assert "BASE_PROMPT_MARKER" in prompt
    assert "HARNESS_MARKER" in prompt
    assert "PERSONALITY_MARKER_TEXT" in prompt


@pytest.mark.asyncio
async def test_unknown_scope_falls_back_to_full():
    prompt = await build_executor_prompt(
        "anything",
        base_prompt="BASE_PROMPT_MARKER",
        context_scope="bogus_scope_value",
        harness_block="HARNESS_MARKER",
        personality=_FakePersonality(),
        profile_name="default",
    )
    assert "BASE_PROMPT_MARKER" in prompt
    assert "PERSONALITY_MARKER_TEXT" in prompt


@pytest.mark.asyncio
async def test_constraints_header_present_when_sources_included():
    prompt = await build_executor_prompt(
        "anything",
        base_prompt="BASE_PROMPT_MARKER",
        context_scope="full",
        harness_block="HARNESS_MARKER",
    )
    assert "## CONSTRAINTS" in prompt


@pytest.mark.asyncio
async def test_constraints_section_contains_skill_content():
    prompt = await build_executor_prompt(
        "anything",
        base_prompt="BASE_PROMPT_MARKER",
        context_scope="full",
        skill_prompt="INJECTED_SKILL_MARKER",
    )
    header_idx = prompt.index("## CONSTRAINTS")
    marker_idx = prompt.index("INJECTED_SKILL_MARKER")
    assert marker_idx > header_idx
