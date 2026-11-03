"""Tool output past the cap is kept on disk; the model sees a head, a tail and the path (H7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from weebot.application.agents.executor._session_scope import get_session_scope
from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.middleware.chain import MiddlewareChain
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.spillover_store_port import SpillRef
from weebot.application.services.spillover import (
    SpilloverMiddleware,
    preview,
    spill_over_budget,
    turn_budget,
)
from weebot.config.constants import MAX_TOOL_OUTPUT_CHARS, TURN_OUTPUT_BUDGET_CHARS
from weebot.core.log_context import session_id_var
from weebot.domain.models.tool_result import ToolResult
from weebot.infrastructure.spillover.file_store import FileSpilloverStore
from weebot.tools.base import BaseTool
from weebot.tools.base import ToolResult as ToolsResult

SESSION = "spill-session"


class _Big(BaseTool):
    name: str = "big"
    description: str = "returns a long text"
    parameters: dict = {"type": "object", "properties": {}}
    size: int = 50_000
    fail: bool = False

    async def execute(self, **kwargs) -> ToolsResult:
        text = "H" * 100 + "m" * (self.size - 200) + "T" * 100
        if self.fail:
            return ToolsResult.error_result(text)
        return ToolsResult(output=text)


@pytest.fixture
def session():
    token = session_id_var.set(SESSION)
    yield SESSION
    session_id_var.reset(token)


def _executor(tmp_path: Path, **tool_kwargs) -> tuple[ToolExecutor, FileSpilloverStore]:
    store = FileSpilloverStore(tmp_path)
    chain = MiddlewareChain([SpilloverMiddleware(store)])
    tools = ToolCollection(_Big(**tool_kwargs))
    return ToolExecutor(tools=tools, middleware_chain=chain), store


@pytest.mark.asyncio
async def test_a_50k_output_becomes_a_preview_and_a_file_holding_all_of_it(tmp_path, session):
    executor, _ = _executor(tmp_path)
    result = await executor.execute_tool("big", {})

    assert len(result.output) <= MAX_TOOL_OUTPUT_CHARS
    assert result.output.startswith("HHH") and "TTT" in result.output[-300:]
    path = Path(result.metadata["spill_path"])
    assert path.read_text(encoding="utf-8").count("m") == 50_000 - 200
    assert str(path) in result.output and "50000 chars" in result.output
    assert "full_output" not in result.metadata  # the transient copy never leaves the executor


@pytest.mark.asyncio
async def test_without_a_chain_the_full_text_is_still_not_left_in_metadata(session):
    result = await ToolExecutor(tools=ToolCollection(_Big())).execute_tool("big", {})
    assert result.metadata["truncated"] is True
    assert "full_output" not in result.metadata


@pytest.mark.asyncio
async def test_a_long_error_spills_too(tmp_path, session):
    executor, _ = _executor(tmp_path, fail=True)
    result = await executor.execute_tool("big", {})

    assert result.is_error and len(result.error) <= 8_000
    assert Path(result.metadata["spill_error_path"]).read_text(encoding="utf-8").count("m") > 0


@pytest.mark.asyncio
async def test_a_short_output_is_left_alone(tmp_path, session):
    executor, _ = _executor(tmp_path, size=1_000)
    result = await executor.execute_tool("big", {})
    assert len(result.output) == 1_000 and "spill_path" not in result.metadata
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_a_spill_file_is_not_a_file_the_session_wrote(tmp_path, session):
    """Reading it back must taint like the original output (D5): never exempt spill paths."""
    executor, _ = _executor(tmp_path)
    result = await executor.execute_tool("big", {})
    assert not get_session_scope().wrote_file(SESSION, result.metadata["spill_path"])


def test_preview_fits_its_cap_and_keeps_head_and_tail():
    ref = SpillRef(path="/x/y.txt", chars=90_000)
    for cap in (20_000, 8_000, 2_000):
        text = "a" * 40_000 + "b" * 50_000
        out = preview(text, cap, ref)
        assert len(out) <= cap
        assert out.startswith("a") and "b" in out[-(cap // 2) :] and "/x/y.txt" in out


@pytest.mark.asyncio
async def test_the_per_turn_budget_spills_the_result_that_crosses_it(tmp_path):
    store = FileSpilloverStore(tmp_path)
    results = [ToolResult(output=chr(97 + i) * 20_000) for i in range(4)]
    await spill_over_budget(store, SESSION, ["t"] * 4, results, 60_000)

    assert [len(r.output) for r in results[:3]] == [20_000] * 3  # 60 000 chars: at the budget
    assert len(results[3].output) <= 2_000  # the fourth crosses it
    assert results[3].metadata["spilled_for_turn_budget"] is True
    assert Path(results[3].metadata["spill_path"]).read_text(encoding="utf-8") == "d" * 20_000
    assert all("spilled_for_turn_budget" not in r.metadata for r in results[:3])


@pytest.mark.asyncio
async def test_a_result_that_already_spilled_keeps_its_file_when_the_budget_shrinks_it(tmp_path):
    store = FileSpilloverStore(tmp_path)
    ref = await store.write(SESSION, "first", "z" * 30_000)
    shown = preview("z" * 30_000, MAX_TOOL_OUTPUT_CHARS, ref)
    result = ToolResult(output=shown, metadata={"spill_path": ref.path})

    await spill_over_budget(store, SESSION, ["t"], [result], budget=100)

    assert len(result.output) <= 2_000 and ref.path in result.output
    assert len(list(Path(ref.path).parent.iterdir())) == 1  # no second copy


@pytest.mark.asyncio
async def test_deleting_a_session_removes_its_spill_directory(tmp_path):
    store = FileSpilloverStore(tmp_path)
    await store.write(SESSION, "a", "one")
    await store.write(SESSION, "b", "two")
    await store.write("other", "c", "three")

    assert await store.purge(SESSION) == 2
    assert [p.name for p in tmp_path.iterdir()] == ["other"]
    assert await store.purge(SESSION) == 0


@pytest.mark.asyncio
async def test_ids_that_try_to_leave_the_directory_stay_inside_it(tmp_path):
    ref = await FileSpilloverStore(tmp_path).write("../../evil", "..\\x/y", "t")
    assert Path(ref.path).resolve().is_relative_to(tmp_path.resolve())


def test_the_budget_comes_from_the_environment_or_the_default(monkeypatch):
    monkeypatch.delenv("WEEBOT_TURN_OUTPUT_BUDGET", raising=False)
    assert turn_budget() == TURN_OUTPUT_BUDGET_CHARS
    monkeypatch.setenv("WEEBOT_TURN_OUTPUT_BUDGET", "1234")
    assert turn_budget() == 1234
    monkeypatch.setenv("WEEBOT_TURN_OUTPUT_BUDGET", "lots")
    assert turn_budget() == TURN_OUTPUT_BUDGET_CHARS
