"""The request prefix (tools, then system) does not change inside a session (H10).

A provider's prompt cache matches the prefix of a request byte for byte. The executor put
per-step text into the system prompt and sent the step's tools in dict order, so every step
sent a new prefix. These tests drive a real executor with a fake model and compare what it
actually sends.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.models.prompt_layout import system_sha, tools_sha
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.plan import Plan, Step
from weebot.infrastructure.adapters.llm.anthropic_caching_adapter import AnthropicCachingAdapter
from weebot.infrastructure.adapters.prompt_prefix_store import InMemoryPromptPrefixStore
from weebot.tools.base import BaseTool, ToolResult


class _Tool(BaseTool):
    async def execute(self, **kw):
        return ToolResult(output=self.name)


def _tool(name: str, **extra_params) -> _Tool:
    props = {"query": {"type": "string"}, **extra_params}
    return _Tool(
        name=name, description=f"{name} tool", parameters={"type": "object", "properties": props}
    )


@dataclass
class _Reply:
    content: str = ""
    tool_calls: list = field(default_factory=list)


def _call(name: str, n: int) -> dict:
    return {"id": f"c{n}", "type": "function", "function": {"name": name, "arguments": "{}"}}


class _Skills:
    """A different skill for each step, so the step context differs."""

    async def retrieve(self, text, top_k=2):
        return [SimpleNamespace(score=0.9, skill_name=f"skill for {text}", content_preview=text)]


def _executor(replies: list[_Reply], seen: list) -> ExecutorAgent:
    tools = ToolCollection(_tool("web_search"), _tool("file_editor"), _tool("image_gen"))
    executor = ExecutorAgent(llm=MagicMock(), tools=tools)
    executor._skill_retriever = _Skills()
    queue = list(replies)

    async def cascade(messages, description):
        seen.append((messages, executor._tools.to_params()))
        return queue.pop(0)

    executor._cascade.call_with_cascade = cascade
    return executor


def _prefix(request) -> tuple[str, str]:
    messages, tools = request
    system = next(m["content"] for m in messages if m["role"] == "system")
    return system_sha(system), tools_sha(tools)


async def _run(executor: ExecutorAgent, plan: Plan, session_id: str = "s1") -> None:
    for step in plan.steps:
        async for _ in executor.execute_step(plan, step, session_id=session_id):
            pass


@pytest.mark.asyncio
async def test_three_turns_of_one_step_send_one_prefix():
    seen: list = []
    step = Step(id="s1", description="search the web for cats")
    executor = _executor(
        [
            _Reply("looking", [_call("web_search", 1)]),
            _Reply("looking again", [_call("web_search", 2)]),
            _Reply("The answer is 42."),
        ],
        seen,
    )

    await _run(executor, Plan(title="t", steps=[step]))

    assert len(seen) == 3
    assert len({_prefix(r) for r in seen}) == 1


@pytest.mark.asyncio
async def test_two_steps_send_one_prefix_when_the_tool_scope_is_per_plan(monkeypatch):
    from weebot.config import feature_flags

    monkeypatch.setattr(feature_flags, "TOOL_SCOPE_GRANULARITY", "plan")
    seen: list = []
    plan = Plan(
        title="t",
        steps=[
            Step(id="s1", description="search the web for cats"),
            Step(id="s2", description="edit the file report.md"),
        ],
    )
    replies = [_Reply("The first answer is 42."), _Reply("The second answer is 7.")]
    executor = _executor(replies, seen)

    await _run(executor, plan)

    assert len(seen) == 2
    assert len({_prefix(r) for r in seen}) == 1


@pytest.mark.asyncio
async def test_what_changes_per_step_leads_the_first_user_message_not_the_system_prompt():
    seen: list = []
    executor = _executor([_Reply("The answer is 42.")], seen)

    await _run(executor, Plan(title="t", steps=[Step(id="s1", description="search the web")]))

    messages, _ = seen[0]
    system = messages[0]["content"]
    first_user = next(m["content"] for m in messages if m["role"] == "user")
    assert "skill for search the web" in first_user and "OUTPUT_ROOT" in first_user
    assert "skill for search the web" not in system and "OUTPUT_ROOT" not in system
    assert "More tools exist" in first_user and "More tools exist" not in system


@pytest.mark.asyncio
async def test_the_store_counts_a_change_between_steps_and_not_a_steady_prefix():
    changes: list[str] = []
    store = InMemoryPromptPrefixStore(on_change=changes.append)
    seen: list = []
    plan = Plan(
        title="t",
        steps=[
            Step(id="s1", description="search the web for cats"),
            Step(id="s2", description="generate a logo image"),
        ],
    )
    replies = [_Reply("The first answer is 42."), _Reply("The second answer is 7.")]
    executor = _executor(replies, seen)
    executor._prompt_prefix = store

    await _run(executor, plan)

    # Per-step scoping (the default) sends a different tool set to each step, and only that.
    assert changes == ["tools"]


def test_the_same_tools_in_any_order_are_the_same_bytes():
    a = ToolCollection(_tool("b_tool", z={"type": "string"}), _tool("a_tool"))
    b = ToolCollection(_tool("a_tool"), _tool("b_tool", z={"type": "string"}))

    assert json.dumps(a.to_params()) == json.dumps(b.to_params())
    assert [p["function"]["name"] for p in a.to_params()] == ["a_tool", "b_tool"]


def test_the_plan_scope_is_the_union_of_its_steps(monkeypatch):
    from weebot.config import feature_flags

    monkeypatch.setattr(feature_flags, "TOOL_SCOPE_GRANULARITY", "plan")
    executor = _executor([], [])
    plan = Plan(
        title="t",
        steps=[
            Step(id="s1", description="search the web for cats"),
            Step(id="s2", description="generate a logo image"),
        ],
    )

    first = executor._scope_tools_for(plan.steps[0], plan)
    names = {p["function"]["name"] for p in executor._tools.to_params()}
    second = executor._scope_tools_for(plan.steps[1], plan)

    assert {"web_search", "image_gen"} <= names
    assert first == second


# ── prefix store ─────────────────────────────────────────────────────────────


def test_the_store_says_what_changed():
    store = InMemoryPromptPrefixStore()
    assert store.record("s", "sys1", "tools1") is None
    assert store.record("s", "sys1", "tools1") is None
    assert store.record("s", "sys1", "tools2") == "tools"
    assert store.record("s", "sys2", "tools2") == "system"
    assert store.record("s", "sys3", "tools3") == "both"


def test_the_store_is_bounded():
    store = InMemoryPromptPrefixStore(max_sessions=2)
    for sid in ("a", "b", "c"):
        store.record(sid, "x", "y")
    # "a" was dropped, so its next record is a first request again, not a change
    assert store.record("a", "other", "other") is None


# ── cache breakpoints ────────────────────────────────────────────────────────


def test_breakpoints_sit_on_the_system_message_and_before_the_newest_assistant_turn():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "step one"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "step two"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "newest"},
    ]

    marked = AnthropicCachingAdapter(enabled=True).prepare_messages(messages)

    cached = [i for i, m in enumerate(marked) if m.get("cache_control")]
    assert cached == [0, 3]
