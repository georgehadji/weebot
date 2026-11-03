"""The memory snapshot is read once per session, and the profile is injected once (H24a)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.application.agents.executor import _step_setup
from weebot.application.services.memory_snapshot_cache import MemorySnapshotCache
from weebot.infrastructure.persistence.filesystem_memory import FileSystemMemoryAdapter
from weebot.tools.persistent_memory import PersistentMemoryTool


@pytest.fixture
def memory(tmp_path):
    adapter = FileSystemMemoryAdapter(memory_dir=tmp_path)
    tool = PersistentMemoryTool(memory=adapter)
    cache = MemorySnapshotCache(lambda: PersistentMemoryTool.load_snapshot(adapter))
    return tool, cache


async def _add(tool, entry):
    return await tool.execute(action="add", file="agent", entry=entry)


@pytest.mark.asyncio
async def test_two_steps_in_one_session_see_identical_text_even_after_a_write(memory):
    tool, cache = memory
    await _add(tool, "first fact")
    step_one = await cache.get("s1")

    await _add(tool, "second fact")

    assert await cache.get("s1") == step_one
    assert "second fact" not in step_one


@pytest.mark.asyncio
async def test_a_new_session_sees_the_write(memory):
    tool, cache = memory
    await _add(tool, "first fact")
    await cache.get("s1")
    await _add(tool, "second fact")

    assert "second fact" in await cache.get("s2")


@pytest.mark.asyncio
async def test_the_session_that_wrote_is_told_when_it_will_see_it(memory):
    tool, _ = memory
    result = await _add(tool, "a fact")
    assert "Added entry" in result.output and "in context from the next session" in result.output


@pytest.mark.asyncio
async def test_forget_makes_the_next_get_read_again(memory):
    tool, cache = memory
    await _add(tool, "first fact")
    await cache.get("s1")
    await _add(tool, "second fact")

    await cache.forget("s1")

    assert "second fact" in await cache.get("s1")


@pytest.mark.asyncio
async def test_with_the_freeze_off_every_step_reads_the_file():
    cache = MemorySnapshotCache(AsyncMock(side_effect=["a", "b"]), frozen=lambda: False)
    assert [await cache.get("s"), await cache.get("s")] == ["a", "b"]


@pytest.mark.asyncio
async def test_the_cache_is_bounded_and_drops_the_least_recently_used():
    load = AsyncMock(return_value="text")
    cache = MemorySnapshotCache(load, max_sessions=2)
    for sid in ("a", "b", "a", "c"):  # "b" is the least recently used when "c" arrives
        await cache.get(sid)
    load.reset_mock()

    await cache.get("a")
    await cache.get("b")

    assert load.await_count == 1  # only "b" had been dropped


@pytest.mark.asyncio
async def test_the_save_note_is_dropped_when_the_freeze_is_off(memory):
    tool, _ = memory
    with patch("weebot.config.feature_flags.MEMORY_SNAPSHOT_FREEZE_ENABLED", False):
        result = await _add(tool, "a fact")
    assert "next session" not in result.output


# ── step setup ───────────────────────────────────────────────────────────────


def _executor(*, repo=None, snapshot=None, session="s1"):
    return SimpleNamespace(
        _scope_tools_for=lambda step: "",
        _load_prompt=lambda: "base",
        _harness_instruction_block=None,
        _skill_prompt=None,
        _skill_retriever=None,
        _behavioral_learner=None,
        _state_repo=repo,
        _personality=None,
        _profile_name="",
        _skills_used=[],
        _memory_snapshot=snapshot,
        _event_bus=None,
        _current_session_id=session,
        _skill_gaps=[],
    )


async def _build(executor):
    step = SimpleNamespace(description="do it", context_scope=None)
    with patch.object(_step_setup, "_seed_conversation", lambda *a: None):
        await _step_setup.build_step_prompts(executor, plan=None, step=step, user_input=None)


@pytest.mark.asyncio
async def test_the_user_profile_appears_once_in_the_system_prompt():
    repo = MagicMock()
    repo.get_memory_entry = AsyncMock(return_value={"entry_text": "likes terse answers"})
    executor = _executor(repo=repo)

    await _build(executor)

    assert executor._system_prompt.count("likes terse answers") == 1


@pytest.mark.asyncio
async def test_the_executor_asks_the_cache_for_its_own_session():
    asked = []

    async def snapshot(session_id):
        asked.append(session_id)
        return "# Persistent Memory"

    executor = _executor(snapshot=snapshot, session="s9")

    await _build(executor)

    assert asked == ["s9"] and executor._system_prompt.endswith("# Persistent Memory")
