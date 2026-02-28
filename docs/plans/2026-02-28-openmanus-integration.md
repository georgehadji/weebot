# OpenManus Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port OpenManus's `BaseTool` protocol, `ToolCallAgent` ReAct loop, `WebSearch`/`StrReplaceEditor`/control tools, and `PlanningFlow` into weebot additively — no existing code deleted, all 73 tests remain green.

**Architecture:** Architecture-first (Phase 1→2→3→4). Phase 1 builds the `BaseTool` foundation and extends domain models. Phase 2 builds `ToolCallWeebotAgent` (ReAct loop using OpenAI function calling). Phase 3 adds new tools. Phase 4 adds `PlanningFlow`. Existing `WeebotAgent`/`RecursiveWeebotAgent` are untouched.

**Tech Stack:** Python 3.12, `openai` SDK (already installed via langchain-openai), `aiohttp` (already installed), `pydantic` v2 (already installed), `pytest-asyncio`.

---

## Progress Tracker

| Task | Feature | Status |
|------|---------|--------|
| 1 | BaseTool + ToolResult + ToolCollection | ⬜ |
| 2 | Message + Memory + AgentState in domain/models.py | ⬜ |
| 3 | ToolCallWeebotAgent (ReAct loop) | ⬜ |
| 4 | WebSearchTool (DuckDuckGo primary, Bing fallback) | ⬜ |
| 5 | StrReplaceEditorTool (view/create/str_replace/insert) | ⬜ |
| 6 | AskHumanTool + TerminateTool | ⬜ |
| 7 | BaseTool wrappers for PowerShellTool + ScreenCaptureTool | ⬜ |
| 8 | PlanningTool + PlanningFlow | ⬜ |
| 9 | Full verification | ⬜ |

---

## Task 1: BaseTool + ToolResult + ToolCollection

**Files:**
- Create: `weebot/tools/base.py`
- Create: `weebot/tools/__init__.py` (update)
- Test: `tests/unit/test_base_tool.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_base_tool.py
import pytest
from weebot.tools.base import BaseTool, ToolResult, ToolCollection


class EchoTool(BaseTool):
    name: str = "echo"
    description: str = "Echoes input back"
    parameters: dict = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Text to echo"}},
        "required": ["text"],
    }

    async def execute(self, text: str) -> ToolResult:
        return ToolResult(output=f"Echo: {text}")


class FailTool(BaseTool):
    name: str = "fail"
    description: str = "Always fails"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        return ToolResult(output="", error="always fails")


def test_tool_result_success():
    r = ToolResult(output="hello")
    assert r.output == "hello"
    assert r.error is None
    assert r.is_error is False


def test_tool_result_error():
    r = ToolResult(output="", error="oops")
    assert r.is_error is True


def test_tool_to_param():
    tool = EchoTool()
    param = tool.to_param()
    assert param["type"] == "function"
    assert param["function"]["name"] == "echo"
    assert "text" in param["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_echo_tool_execute():
    tool = EchoTool()
    result = await tool.execute(text="hello")
    assert result.output == "Echo: hello"


@pytest.mark.asyncio
async def test_tool_collection_execute():
    col = ToolCollection(EchoTool(), FailTool())
    result = await col.execute("echo", text="world")
    assert result.output == "Echo: world"


@pytest.mark.asyncio
async def test_tool_collection_unknown():
    col = ToolCollection(EchoTool())
    result = await col.execute("nonexistent")
    assert result.is_error
    assert "nonexistent" in result.error


def test_tool_collection_to_params():
    col = ToolCollection(EchoTool(), FailTool())
    params = col.to_params()
    assert len(params) == 2
    assert params[0]["function"]["name"] == "echo"
```

**Step 2: Run to verify it fails**

Run: `pytest tests/unit/test_base_tool.py -v`
Expected: ImportError — `weebot.tools.base` does not exist

**Step 3: Implement `weebot/tools/base.py`**

```python
"""BaseTool protocol — OpenManus-style function-calling tools for weebot."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from pydantic import BaseModel


@dataclass
class ToolResult:
    """Result from any tool execution."""
    output: str
    error: str | None = None
    base64_image: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def __str__(self) -> str:
        if self.is_error:
            return f"ERROR: {self.error}"
        return self.output


class BaseTool(ABC, BaseModel):
    """Base class for all weebot function-calling tools."""
    name: str
    description: str
    parameters: dict  # JSON Schema object

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...

    def to_param(self) -> dict:
        """Convert to OpenAI function spec for tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    class Config:
        arbitrary_types_allowed = True


class ToolCollection:
    """Registry of tools; dispatches execute() by name."""

    def __init__(self, *tools: BaseTool) -> None:
        self._tools: dict[str, BaseTool] = {t.name: t for t in tools}

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def to_params(self) -> list[dict]:
        return [t.to_param() for t in self._tools.values()]

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        if name not in self._tools:
            return ToolResult(output="", error=f"Unknown tool: {name!r}")
        try:
            return await self._tools[name].execute(**kwargs)
        except Exception as exc:
            return ToolResult(output="", error=str(exc))
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_base_tool.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add weebot/tools/base.py tests/unit/test_base_tool.py
git commit -m "feat: add BaseTool protocol with ToolResult and ToolCollection"
```

---

## Task 2: Message + Memory + AgentState in domain/models.py

**Files:**
- Modify: `weebot/domain/models.py` (append — do NOT remove existing code)
- Create: `weebot/domain/__init__.py` (if missing)
- Test: `tests/unit/test_domain_models.py` (extend existing file)

**Step 1: Write the failing tests** (append to existing test file)

```python
# Append to tests/unit/test_domain_models.py
from weebot.domain.models import Role, Message, Memory, AgentState


def test_message_user():
    msg = Message(role=Role.USER, content="hello")
    assert msg.role == Role.USER
    assert msg.to_openai_dict()["role"] == "user"
    assert msg.to_openai_dict()["content"] == "hello"


def test_message_tool():
    msg = Message(role=Role.TOOL, content="result", tool_call_id="call_abc")
    d = msg.to_openai_dict()
    assert d["role"] == "tool"
    assert d["tool_call_id"] == "call_abc"


def test_memory_add_and_limit():
    mem = Memory(max_messages=3)
    for i in range(5):
        mem.add(Message(role=Role.USER, content=str(i)))
    # System message (if any) preserved; non-system capped at 3
    non_system = [m for m in mem.messages if m.role != Role.SYSTEM]
    assert len(non_system) <= 3


def test_memory_to_openai_format():
    mem = Memory()
    mem.add(Message(role=Role.SYSTEM, content="sys"))
    mem.add(Message(role=Role.USER, content="hi"))
    fmt = mem.to_openai_format()
    assert fmt[0]["role"] == "system"
    assert fmt[1]["role"] == "user"


def test_agent_state_values():
    assert AgentState.IDLE.value == "idle"
    assert AgentState.RUNNING.value == "running"
    assert AgentState.FINISHED.value == "finished"
    assert AgentState.ERROR.value == "error"
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_domain_models.py -v -k "test_message or test_memory or test_agent_state"`
Expected: ImportError for `Role`, `Message`, `Memory`, `AgentState`

**Step 3: Append to `weebot/domain/models.py`**

Add the following at the END of the existing file (after the last class):

```python
# ---------------------------------------------------------------------------
# OpenManus-style Message / Memory / AgentState (added 2026-02-28)
# ---------------------------------------------------------------------------
from enum import Enum as _Enum
from typing import Any as _Any


class Role(_Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentState(_Enum):
    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class ToolCallSpec:
    """Minimal spec for a single tool call from LLM response."""
    id: str
    name: str
    arguments: str  # raw JSON string


@dataclass
class Message:
    """A single chat message in the agent's memory."""
    role: Role
    content: str = ""
    tool_calls: list[ToolCallSpec] = field(default_factory=list)
    tool_call_id: str | None = None

    def to_openai_dict(self) -> dict[str, _Any]:
        d: dict[str, _Any] = {"role": self.role.value, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role=Role.USER, content=content)


@dataclass
class Memory:
    """Conversation memory with automatic truncation."""
    max_messages: int = 100
    messages: list[Message] = field(default_factory=list)

    def add(self, message: Message) -> None:
        self.messages.append(message)
        self._trim()

    def _trim(self) -> None:
        """Keep system messages; cap non-system at max_messages."""
        system = [m for m in self.messages if m.role == Role.SYSTEM]
        non_system = [m for m in self.messages if m.role != Role.SYSTEM]
        if len(non_system) > self.max_messages:
            non_system = non_system[-self.max_messages:]
        self.messages = system + non_system

    def to_openai_format(self) -> list[dict[str, _Any]]:
        return [m.to_openai_dict() for m in self.messages]

    def clear(self) -> None:
        system = [m for m in self.messages if m.role == Role.SYSTEM]
        self.messages = system
```

**Step 4: Ensure `weebot/domain/__init__.py` exists**

If it doesn't exist, create it:
```python
# weebot/domain/__init__.py
```

**Step 5: Run all tests**

Run: `pytest tests/unit/test_domain_models.py -v`
Expected: All tests PASS (both old and new)

**Step 6: Commit**

```bash
git add weebot/domain/models.py weebot/domain/__init__.py tests/unit/test_domain_models.py
git commit -m "feat: add Message, Memory, AgentState, Role to domain models"
```

---

## Task 3: ToolCallWeebotAgent (ReAct Loop)

**Files:**
- Create: `weebot/core/tool_agent.py`
- Test: `tests/unit/test_tool_agent.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_tool_agent.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from weebot.tools.base import BaseTool, ToolResult, ToolCollection
from weebot.domain.models import AgentState
from weebot.core.tool_agent import ToolCallWeebotAgent


class UpperTool(BaseTool):
    name: str = "uppercase"
    description: str = "Converts text to uppercase"
    parameters: dict = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, text: str) -> ToolResult:
        return ToolResult(output=text.upper())


def _make_finish_response(content: str):
    """OpenAI-like response with no tool calls (agent finishes)."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_tool_call_response(tool_name: str, args: dict, call_id: str = "call_1"):
    """OpenAI-like response with one tool call."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args)
    msg = MagicMock()
    msg.content = ""
    msg.tool_calls = [tc]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_agent_finishes_without_tools():
    """Agent returns LLM content when no tool calls are made."""
    agent = ToolCallWeebotAgent(tools=ToolCollection(UpperTool()))

    mock_create = AsyncMock(return_value=_make_finish_response("Done!"))
    with patch.object(agent._client.chat.completions, "create", mock_create):
        result = await agent.run("say done")

    assert result == "Done!"
    assert agent.state == AgentState.FINISHED


@pytest.mark.asyncio
async def test_agent_calls_tool_then_finishes():
    """Agent calls tool, gets result, then finishes on next LLM call."""
    agent = ToolCallWeebotAgent(tools=ToolCollection(UpperTool()))

    responses = [
        _make_tool_call_response("uppercase", {"text": "hello"}, "call_1"),
        _make_finish_response("I uppercased it: HELLO"),
    ]
    mock_create = AsyncMock(side_effect=responses)
    with patch.object(agent._client.chat.completions, "create", mock_create):
        result = await agent.run("uppercase hello")

    assert "HELLO" in result
    assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_agent_handles_tool_error_gracefully():
    """Agent continues when tool returns an error."""

    class BrokenTool(BaseTool):
        name: str = "broken"
        description: str = "Broken"
        parameters: dict = {"type": "object", "properties": {}}

        async def execute(self) -> ToolResult:
            raise RuntimeError("tool crashed")

    agent = ToolCallWeebotAgent(tools=ToolCollection(BrokenTool()))
    responses = [
        _make_tool_call_response("broken", {}, "call_1"),
        _make_finish_response("I encountered an error"),
    ]
    mock_create = AsyncMock(side_effect=responses)
    with patch.object(agent._client.chat.completions, "create", mock_create):
        result = await agent.run("break it")

    assert result  # agent recovered


def test_agent_initial_state():
    agent = ToolCallWeebotAgent(tools=ToolCollection())
    assert agent.state == AgentState.IDLE
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_tool_agent.py -v`
Expected: ImportError — `weebot.core.tool_agent` does not exist

**Step 3: Implement `weebot/core/tool_agent.py`**

```python
"""ToolCallWeebotAgent — ReAct loop with OpenAI function calling."""
from __future__ import annotations
import json
import os
from typing import Any

from openai import AsyncOpenAI

from weebot.tools.base import ToolCollection, ToolResult
from weebot.domain.models import (
    AgentState, Memory, Message, Role, ToolCallSpec
)

SYSTEM_PROMPT = """You are weebot, an autonomous AI agent for Windows 11.
You have access to tools to help complete tasks. Use them when needed.
When you are finished, respond with a clear summary of what you accomplished.
"""

MAX_STEPS = 30


class ToolCallWeebotAgent:
    """
    ReAct-style agent using OpenAI function calling.

    Loop: think() → act() → think() → ... → finish
    - think(): calls LLM with current memory + tool specs
    - act(): executes tool calls returned by LLM
    - finish: LLM returns a message with no tool_calls
    """

    def __init__(
        self,
        tools: ToolCollection,
        system_prompt: str = SYSTEM_PROMPT,
        model: str | None = None,
        max_steps: int = MAX_STEPS,
    ) -> None:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        base_url = None
        if not os.getenv("OPENAI_API_KEY") and os.getenv("DEEPSEEK_API_KEY"):
            base_url = "https://api.deepseek.com"

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model or os.getenv("WEEBOT_MODEL", "gpt-4o-mini")
        self.tools = tools
        self.max_steps = max_steps
        self.memory = Memory()
        self.state = AgentState.IDLE

        if system_prompt:
            self.memory.add(Message.system(system_prompt))

    async def think(self) -> bool:
        """
        Call LLM with current memory.
        Returns True if LLM issued tool calls, False if it gave a final response.
        """
        tool_params = self.tools.to_params()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self.memory.to_openai_format(),
        }
        if tool_params:
            kwargs["tools"] = tool_params
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        # Convert to our Message format
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCallSpec(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ))

        self.memory.add(Message(
            role=Role.ASSISTANT,
            content=msg.content or "",
            tool_calls=tool_calls,
        ))

        return bool(tool_calls)

    async def act(self) -> None:
        """Execute tool calls from the last assistant message."""
        last = self.memory.messages[-1]
        for tc in last.tool_calls:
            try:
                args = json.loads(tc.arguments)
            except json.JSONDecodeError:
                args = {}

            result: ToolResult = await self.tools.execute(tc.name, **args)

            self.memory.add(Message(
                role=Role.TOOL,
                content=str(result),
                tool_call_id=tc.id,
            ))

    async def run(self, prompt: str) -> str:
        """Run agent until finished or max_steps reached."""
        self.state = AgentState.RUNNING
        self.memory.add(Message.user(prompt))

        for _ in range(self.max_steps):
            has_tool_calls = await self.think()
            if not has_tool_calls:
                self.state = AgentState.FINISHED
                return self.memory.messages[-1].content or ""
            await self.act()

        self.state = AgentState.FINISHED
        return "Max steps reached without a final answer."
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_tool_agent.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add weebot/core/tool_agent.py tests/unit/test_tool_agent.py
git commit -m "feat: add ToolCallWeebotAgent with ReAct loop (think/act)"
```

---

## Task 4: WebSearchTool

**Files:**
- Create: `weebot/tools/web_search.py`
- Test: `tests/unit/test_web_search.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_web_search.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from weebot.tools.web_search import WebSearchTool, DuckDuckGoEngine, BingEngine


def test_web_search_tool_to_param():
    tool = WebSearchTool()
    p = tool.to_param()
    assert p["function"]["name"] == "web_search"
    assert "query" in p["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_web_search_returns_results():
    tool = WebSearchTool()
    mock_results = [
        {"title": "Test", "url": "https://example.com", "snippet": "A test page"},
    ]
    with patch.object(tool, "_search_duckduckgo", AsyncMock(return_value=mock_results)):
        result = await tool.execute(query="test query", num_results=1)
    assert "Test" in result.output
    assert "example.com" in result.output


@pytest.mark.asyncio
async def test_web_search_fallback_on_error():
    tool = WebSearchTool()
    bing_results = [{"title": "Bing", "url": "https://bing.com", "snippet": "bing"}]
    with patch.object(tool, "_search_duckduckgo", AsyncMock(side_effect=Exception("DDG down"))):
        with patch.object(tool, "_search_bing", AsyncMock(return_value=bing_results)):
            result = await tool.execute(query="fallback test")
    assert "Bing" in result.output


@pytest.mark.asyncio
async def test_web_search_all_fail():
    tool = WebSearchTool()
    with patch.object(tool, "_search_duckduckgo", AsyncMock(side_effect=Exception("DDG down"))):
        with patch.object(tool, "_search_bing", AsyncMock(side_effect=Exception("Bing down"))):
            result = await tool.execute(query="fail test")
    assert result.is_error
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_web_search.py -v`
Expected: ImportError

**Step 3: Implement `weebot/tools/web_search.py`**

```python
"""WebSearchTool — multi-engine search with DuckDuckGo primary, Bing fallback."""
from __future__ import annotations
import os
from typing import Any

import aiohttp

from weebot.tools.base import BaseTool, ToolResult

_DDG_URL = "https://html.duckduckgo.com/html/"
_BING_URL = "https://api.bing.microsoft.com/v7.0/search"


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "Search the web for current information. "
        "Returns titles, URLs, and snippets from top results."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default 5, max 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, num_results: int = 5) -> ToolResult:
        num_results = min(num_results, 10)
        errors: list[str] = []

        # Primary: DuckDuckGo (no key required)
        try:
            results = await self._search_duckduckgo(query, num_results)
            return ToolResult(output=self._format(results))
        except Exception as e:
            errors.append(f"DuckDuckGo: {e}")

        # Fallback: Bing (requires BING_API_KEY)
        try:
            results = await self._search_bing(query, num_results)
            return ToolResult(output=self._format(results))
        except Exception as e:
            errors.append(f"Bing: {e}")

        return ToolResult(output="", error=f"All search engines failed: {'; '.join(errors)}")

    async def _search_duckduckgo(
        self, query: str, num_results: int
    ) -> list[dict[str, str]]:
        """Parse DuckDuckGo HTML results."""
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                _DDG_URL, data={"q": query}, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                html = await resp.text()

        # Simple extraction without BeautifulSoup
        results: list[dict[str, str]] = []
        import re
        # DDG HTML pattern: result links and snippets
        link_pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="result__snippet"[^>]*>([^<]+)</a>'
        )
        links = link_pattern.findall(html)
        snippets = [m.strip() for m in snippet_pattern.findall(html)]

        for i, (url, title) in enumerate(links[:num_results]):
            results.append({
                "title": title.strip(),
                "url": url,
                "snippet": snippets[i] if i < len(snippets) else "",
            })

        if not results:
            raise ValueError("No results parsed from DuckDuckGo HTML")
        return results

    async def _search_bing(
        self, query: str, num_results: int
    ) -> list[dict[str, str]]:
        """Call Bing Web Search API (requires BING_API_KEY env var)."""
        key = os.getenv("BING_API_KEY")
        if not key:
            raise ValueError("BING_API_KEY not set")
        headers = {"Ocp-Apim-Subscription-Key": key}
        params = {"q": query, "count": num_results, "mkt": "en-US"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                _BING_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()

        results = []
        for item in data.get("webPages", {}).get("value", [])[:num_results]:
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
            })
        if not results:
            raise ValueError("No results from Bing")
        return results

    def _format(self, results: list[dict[str, str]]) -> str:
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   URL: {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines).strip()


# Keep these as aliases for testing convenience
DuckDuckGoEngine = WebSearchTool
BingEngine = WebSearchTool
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_web_search.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add weebot/tools/web_search.py tests/unit/test_web_search.py
git commit -m "feat: add WebSearchTool with DuckDuckGo primary and Bing fallback"
```

---

## Task 5: StrReplaceEditorTool

**Files:**
- Create: `weebot/tools/file_editor.py`
- Test: `tests/unit/test_file_editor.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_file_editor.py
import pytest
from pathlib import Path
from weebot.tools.file_editor import StrReplaceEditorTool


@pytest.fixture
def editor():
    return StrReplaceEditorTool()


@pytest.mark.asyncio
async def test_create_file(editor, tmp_path):
    path = str(tmp_path / "test.txt")
    result = await editor.execute(command="create", path=path, file_text="hello world")
    assert not result.is_error
    assert Path(path).read_text() == "hello world"


@pytest.mark.asyncio
async def test_view_file(editor, tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("line1\nline2\nline3")
    result = await editor.execute(command="view", path=str(path))
    assert not result.is_error
    assert "line1" in result.output
    assert "line2" in result.output


@pytest.mark.asyncio
async def test_view_directory(editor, tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    result = await editor.execute(command="view", path=str(tmp_path))
    assert not result.is_error
    assert "a.py" in result.output


@pytest.mark.asyncio
async def test_str_replace(editor, tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("foo bar baz")
    result = await editor.execute(
        command="str_replace", path=str(path),
        old_str="bar", new_str="QUX"
    )
    assert not result.is_error
    assert path.read_text() == "foo QUX baz"


@pytest.mark.asyncio
async def test_str_replace_not_found(editor, tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("hello")
    result = await editor.execute(
        command="str_replace", path=str(path),
        old_str="NOTHERE", new_str="x"
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_insert_line(editor, tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("line1\nline3")
    result = await editor.execute(
        command="insert", path=str(path),
        insert_line=1, new_str="line2"
    )
    assert not result.is_error
    assert "line2" in path.read_text()


@pytest.mark.asyncio
async def test_unknown_command(editor):
    result = await editor.execute(command="delete", path="/tmp/x")
    assert result.is_error
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_file_editor.py -v`
Expected: ImportError

**Step 3: Implement `weebot/tools/file_editor.py`**

```python
"""StrReplaceEditorTool — file view/create/edit operations."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from weebot.tools.base import BaseTool, ToolResult


class StrReplaceEditorTool(BaseTool):
    name: str = "file_editor"
    description: str = (
        "View, create, or edit files on the local filesystem. "
        "Commands: view (read file or list dir), create (write new file), "
        "str_replace (find+replace in file), insert (add lines at position)."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["view", "create", "str_replace", "insert"],
                "description": "Operation to perform",
            },
            "path": {"type": "string", "description": "Absolute or relative file/dir path"},
            "file_text": {"type": "string", "description": "Content for 'create' command"},
            "old_str": {"type": "string", "description": "Text to find for 'str_replace'"},
            "new_str": {"type": "string", "description": "Replacement text"},
            "insert_line": {
                "type": "integer",
                "description": "Line number after which to insert (0 = beginning) for 'insert'",
            },
            "view_range": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[start_line, end_line] for partial view",
            },
        },
        "required": ["command", "path"],
    }

    async def execute(self, command: str, path: str, **kwargs: Any) -> ToolResult:
        p = Path(path)
        if command == "view":
            return self._view(p, kwargs.get("view_range"))
        elif command == "create":
            return self._create(p, kwargs.get("file_text", ""))
        elif command == "str_replace":
            return self._str_replace(p, kwargs.get("old_str", ""), kwargs.get("new_str", ""))
        elif command == "insert":
            return self._insert(p, kwargs.get("insert_line", 0), kwargs.get("new_str", ""))
        else:
            return ToolResult(output="", error=f"Unknown command: {command!r}")

    def _view(self, path: Path, view_range: list[int] | None) -> ToolResult:
        if path.is_dir():
            items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = [f"{'DIR' if p.is_dir() else 'FILE':4}  {p.name}" for p in items]
            return ToolResult(output="\n".join(lines) or "(empty directory)")
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        numbered = [f"{i+1:4}: {line}" for i, line in enumerate(content.splitlines())]
        if view_range and len(view_range) == 2:
            start, end = view_range
            numbered = numbered[start - 1: end]
        return ToolResult(output="\n".join(numbered))

    def _create(self, path: Path, text: str) -> ToolResult:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return ToolResult(output=f"Created {path} ({len(text)} chars)")

    def _str_replace(self, path: Path, old_str: str, new_str: str) -> ToolResult:
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        content = path.read_text(encoding="utf-8")
        if old_str not in content:
            return ToolResult(output="", error=f"String not found in {path}: {old_str!r}")
        new_content = content.replace(old_str, new_str, 1)
        path.write_text(new_content, encoding="utf-8")
        return ToolResult(output=f"Replaced in {path}")

    def _insert(self, path: Path, insert_line: int, new_str: str) -> ToolResult:
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = new_str.splitlines(keepends=True)
        # Ensure each new line ends with newline
        new_lines = [l if l.endswith("\n") else l + "\n" for l in new_lines]
        lines[insert_line:insert_line] = new_lines
        path.write_text("".join(lines), encoding="utf-8")
        return ToolResult(output=f"Inserted {len(new_lines)} line(s) at line {insert_line} in {path}")
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_file_editor.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add weebot/tools/file_editor.py tests/unit/test_file_editor.py
git commit -m "feat: add StrReplaceEditorTool (view/create/str_replace/insert)"
```

---

## Task 6: AskHumanTool + TerminateTool

**Files:**
- Create: `weebot/tools/control.py`
- Test: `tests/unit/test_control_tools.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_control_tools.py
import pytest
from unittest.mock import patch
from weebot.tools.control import AskHumanTool, TerminateTool
from weebot.domain.models import AgentState


def test_terminate_to_param():
    t = TerminateTool()
    p = t.to_param()
    assert p["function"]["name"] == "terminate"
    assert "reason" in p["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_terminate_returns_reason():
    t = TerminateTool()
    result = await t.execute(reason="Task complete")
    assert not result.is_error
    assert "Task complete" in result.output


def test_ask_human_to_param():
    t = AskHumanTool()
    p = t.to_param()
    assert p["function"]["name"] == "ask_human"


@pytest.mark.asyncio
async def test_ask_human_returns_input():
    t = AskHumanTool()
    with patch("builtins.input", return_value="yes"):
        result = await t.execute(question="Continue?")
    assert result.output == "yes"
    assert not result.is_error
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_control_tools.py -v`
Expected: ImportError

**Step 3: Implement `weebot/tools/control.py`**

```python
"""Control tools: AskHumanTool (human-in-the-loop) and TerminateTool."""
from __future__ import annotations
import asyncio
from weebot.tools.base import BaseTool, ToolResult


class TerminateTool(BaseTool):
    """Signals the agent that the task is complete."""
    name: str = "terminate"
    description: str = (
        "Signal that the task is complete. Call this when you have finished "
        "and have a final answer. Provide a clear reason/summary."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Why the task is finished / final result summary",
            }
        },
        "required": ["reason"],
    }

    async def execute(self, reason: str) -> ToolResult:
        return ToolResult(output=f"Task terminated: {reason}")


class AskHumanTool(BaseTool):
    """Pauses the agent to ask the human operator a question."""
    name: str = "ask_human"
    description: str = (
        "Ask the human operator a question and wait for their input. "
        "Use this when you need clarification, approval, or data you cannot find."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the human",
            }
        },
        "required": ["question"],
    }

    async def execute(self, question: str) -> ToolResult:
        # Run blocking input() in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(None, input, f"\n[weebot asks] {question}\nYour answer: ")
        return ToolResult(output=answer.strip())
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_control_tools.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add weebot/tools/control.py tests/unit/test_control_tools.py
git commit -m "feat: add AskHumanTool and TerminateTool"
```

---

## Task 7: BaseTool Wrappers for Existing Tools

**Files:**
- Modify: `weebot/tools/powershell_tool.py` (append wrapper class)
- Modify: `weebot/tools/screen_tool.py` (append wrapper class + commit pending fix)
- Test: `tests/unit/test_tool_wrappers.py`

**Step 1: Commit the pending fix in screen_tool.py first**

```bash
git add weebot/tools/screen_tool.py
git commit -m "fix: validate negative monitor_index in ScreenCaptureTool"
```

**Step 2: Write the failing test**

```python
# tests/unit/test_tool_wrappers.py
import pytest
from unittest.mock import patch, MagicMock
from weebot.tools.powershell_tool import PowerShellBaseTool
from weebot.tools.screen_tool import ScreenCaptureBaseTool


def test_powershell_base_tool_to_param():
    t = PowerShellBaseTool()
    p = t.to_param()
    assert p["function"]["name"] == "powershell"
    assert "command" in p["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_powershell_base_tool_execute():
    t = PowerShellBaseTool()
    with patch.object(t._inner, "_run", return_value="OK output"):
        result = await t.execute(command="echo hello")
    assert result.output == "OK output"
    assert not result.is_error


def test_screen_capture_base_tool_to_param():
    t = ScreenCaptureBaseTool()
    p = t.to_param()
    assert p["function"]["name"] == "screen_capture"
    assert "monitor_index" in p["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_screen_capture_base_tool_success():
    t = ScreenCaptureBaseTool()
    fake_result = {"success": True, "output": "Captured monitor 0 (1920x1080)", "data": b"PNG"}
    with patch.object(t._inner, "capture", return_value=fake_result):
        result = await t.execute(monitor_index=0)
    assert not result.is_error
    assert "Captured" in result.output


@pytest.mark.asyncio
async def test_screen_capture_base_tool_failure():
    t = ScreenCaptureBaseTool()
    fake_result = {"success": False, "output": "mss not installed", "data": None}
    with patch.object(t._inner, "capture", return_value=fake_result):
        result = await t.execute(monitor_index=0)
    assert result.is_error
```

**Step 3: Run to verify failure**

Run: `pytest tests/unit/test_tool_wrappers.py -v`
Expected: ImportError

**Step 4: Append `PowerShellBaseTool` to `weebot/tools/powershell_tool.py`**

Read the file first to find the end, then append:

```python
# --- Append at end of weebot/tools/powershell_tool.py ---

from weebot.tools.base import BaseTool, ToolResult


class PowerShellBaseTool(BaseTool):
    """BaseTool wrapper around PowerShellTool for function-calling agents."""
    name: str = "powershell"
    description: str = (
        "Execute a PowerShell command on Windows. "
        "Use for file operations, system info, process management, registry queries."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "PowerShell command or script to execute",
            }
        },
        "required": ["command"],
    }

    def __init__(self, **data):
        super().__init__(**data)
        object.__setattr__(self, "_inner", PowerShellTool())

    async def execute(self, command: str) -> ToolResult:
        try:
            output = self._inner._run(command)
            return ToolResult(output=output)
        except Exception as e:
            return ToolResult(output="", error=str(e))

    class Config:
        arbitrary_types_allowed = True
```

**Step 5: Append `ScreenCaptureBaseTool` to `weebot/tools/screen_tool.py`**

```python
# --- Append at end of weebot/tools/screen_tool.py ---

from weebot.tools.base import BaseTool, ToolResult


class ScreenCaptureBaseTool(BaseTool):
    """BaseTool wrapper around ScreenCaptureTool for function-calling agents."""
    name: str = "screen_capture"
    description: str = (
        "Capture a screenshot of a connected monitor. "
        "Returns capture confirmation. Use monitor_index=0 for primary screen."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "monitor_index": {
                "type": "integer",
                "description": "Monitor index (0 = primary, 1+ = secondary)",
                "default": 0,
            },
            "save_path": {
                "type": "string",
                "description": "Optional file path to save the screenshot PNG",
            },
        },
    }

    def __init__(self, **data):
        super().__init__(**data)
        object.__setattr__(self, "_inner", ScreenCaptureTool())

    async def execute(self, monitor_index: int = 0, save_path: str | None = None) -> ToolResult:
        result = self._inner.capture(monitor_index=monitor_index, save_path=save_path)
        if result["success"]:
            return ToolResult(output=result["output"])
        return ToolResult(output="", error=result["output"])

    class Config:
        arbitrary_types_allowed = True
```

**Step 6: Run tests**

Run: `pytest tests/unit/test_tool_wrappers.py -v`
Expected: All 5 tests PASS

Run: `pytest tests/ -q`
Expected: All existing tests still PASS

**Step 7: Commit**

```bash
git add weebot/tools/powershell_tool.py weebot/tools/screen_tool.py tests/unit/test_tool_wrappers.py
git commit -m "feat: add BaseTool wrappers for PowerShellTool and ScreenCaptureTool"
```

---

## Task 8: PlanningTool + PlanningFlow

**Files:**
- Create: `weebot/flow/__init__.py`
- Create: `weebot/flow/planning.py`
- Test: `tests/unit/test_planning.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_planning.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from weebot.flow.planning import PlanningTool, PlanningFlow
from weebot.tools.base import ToolCollection, ToolResult, BaseTool


# --- PlanningTool tests ---

@pytest.mark.asyncio
async def test_planning_tool_create():
    tool = PlanningTool()
    result = await tool.execute(
        command="create",
        plan_id="p1",
        title="My Plan",
        steps=["step 1", "step 2"],
    )
    assert not result.is_error
    assert "My Plan" in result.output


@pytest.mark.asyncio
async def test_planning_tool_update_step():
    tool = PlanningTool()
    await tool.execute(command="create", plan_id="p1", title="T", steps=["s1"])
    result = await tool.execute(
        command="update_step", plan_id="p1", step_index=0, status="completed"
    )
    assert not result.is_error


@pytest.mark.asyncio
async def test_planning_tool_get():
    tool = PlanningTool()
    await tool.execute(command="create", plan_id="p1", title="T", steps=["s1", "s2"])
    result = await tool.execute(command="get", plan_id="p1")
    assert "s1" in result.output
    assert "s2" in result.output


@pytest.mark.asyncio
async def test_planning_tool_missing_plan():
    tool = PlanningTool()
    result = await tool.execute(command="get", plan_id="nonexistent")
    assert result.is_error


# --- PlanningFlow tests ---

class EchoTool(BaseTool):
    name: str = "echo"
    description: str = "Echo"
    parameters: dict = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, text: str) -> ToolResult:
        return ToolResult(output=f"Echo: {text}")


def _finish_response(content: str):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_planning_flow_run():
    flow = PlanningFlow(tools=ToolCollection(EchoTool()))
    mock_create = AsyncMock(return_value=_finish_response("Plan complete"))
    with patch.object(flow._agent._client.chat.completions, "create", mock_create):
        result = await flow.run("Do something")
    assert result  # got some output
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_planning.py -v`
Expected: ImportError

**Step 3: Create `weebot/flow/__init__.py`**

```python
# weebot/flow/__init__.py
```

**Step 4: Implement `weebot/flow/planning.py`**

```python
"""PlanningTool + PlanningFlow — multi-step plan generation and execution."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from weebot.tools.base import BaseTool, ToolCollection, ToolResult
from weebot.core.tool_agent import ToolCallWeebotAgent

PLANNING_SYSTEM_PROMPT = """You are weebot, an autonomous AI agent for Windows 11.
Your job is to help complete tasks by breaking them into steps and executing each step.
When you have a final answer or the task is done, provide a clear summary.
"""


# ---------------------------------------------------------------------------
# PlanningTool — in-memory plan CRUD
# ---------------------------------------------------------------------------

@dataclass
class _PlanStep:
    description: str
    status: str = "pending"  # pending | running | completed | failed


@dataclass
class _Plan:
    plan_id: str
    title: str
    steps: list[_PlanStep] = field(default_factory=list)


class PlanningTool(BaseTool):
    """In-memory CRUD for agent plans (create/update_step/get/clear)."""
    name: str = "planning"
    description: str = (
        "Manage a task plan. Commands: create (new plan with steps), "
        "update_step (mark step status), get (view current plan), clear (delete plan)."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["create", "update_step", "get", "clear"],
            },
            "plan_id": {"type": "string", "description": "Unique plan identifier"},
            "title": {"type": "string", "description": "Plan title (for create)"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of step descriptions (for create)",
            },
            "step_index": {"type": "integer", "description": "0-based step index (for update_step)"},
            "status": {
                "type": "string",
                "enum": ["pending", "running", "completed", "failed"],
                "description": "New status for the step (for update_step)",
            },
        },
        "required": ["command", "plan_id"],
    }

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        object.__setattr__(self, "_plans", {})

    @property
    def _store(self) -> dict[str, _Plan]:
        return object.__getattribute__(self, "_plans")

    async def execute(self, command: str, plan_id: str, **kwargs: Any) -> ToolResult:
        if command == "create":
            return self._create(plan_id, kwargs.get("title", ""), kwargs.get("steps", []))
        elif command == "update_step":
            return self._update_step(plan_id, kwargs.get("step_index", 0), kwargs.get("status", "completed"))
        elif command == "get":
            return self._get(plan_id)
        elif command == "clear":
            self._store.pop(plan_id, None)
            return ToolResult(output=f"Plan {plan_id!r} cleared")
        return ToolResult(output="", error=f"Unknown command: {command!r}")

    def _create(self, plan_id: str, title: str, steps: list[str]) -> ToolResult:
        plan = _Plan(plan_id=plan_id, title=title,
                     steps=[_PlanStep(description=s) for s in steps])
        self._store[plan_id] = plan
        lines = [f"Plan: {title}", "Steps:"]
        for i, s in enumerate(plan.steps):
            lines.append(f"  {i}. [ ] {s.description}")
        return ToolResult(output="\n".join(lines))

    def _update_step(self, plan_id: str, step_index: int, status: str) -> ToolResult:
        if plan_id not in self._store:
            return ToolResult(output="", error=f"Plan not found: {plan_id!r}")
        plan = self._store[plan_id]
        if step_index >= len(plan.steps):
            return ToolResult(output="", error=f"Step index {step_index} out of range")
        plan.steps[step_index].status = status
        return ToolResult(output=f"Step {step_index} → {status}")

    def _get(self, plan_id: str) -> ToolResult:
        if plan_id not in self._store:
            return ToolResult(output="", error=f"Plan not found: {plan_id!r}")
        plan = self._store[plan_id]
        status_icon = {"pending": "[ ]", "running": "[~]", "completed": "[x]", "failed": "[!]"}
        lines = [f"Plan: {plan.title}"]
        for i, s in enumerate(plan.steps):
            icon = status_icon.get(s.status, "[ ]")
            lines.append(f"  {i}. {icon} {s.description}")
        return ToolResult(output="\n".join(lines))

    class Config:
        arbitrary_types_allowed = True


# ---------------------------------------------------------------------------
# PlanningFlow — orchestrates ToolCallWeebotAgent with a planning tool
# ---------------------------------------------------------------------------

class PlanningFlow:
    """
    High-level flow: creates a ToolCallWeebotAgent that has access to
    PlanningTool + any execution tools, then runs the agent on the prompt.
    The agent is expected to create a plan, execute steps, and terminate.
    """

    def __init__(self, tools: ToolCollection | None = None) -> None:
        planning_tool = PlanningTool()
        all_tools: list[BaseTool] = [planning_tool]
        if tools:
            all_tools.extend(list(tools))

        self._agent = ToolCallWeebotAgent(
            tools=ToolCollection(*all_tools),
            system_prompt=PLANNING_SYSTEM_PROMPT,
        )

    async def run(self, prompt: str) -> str:
        """Execute the planning flow for a given prompt."""
        return await self._agent.run(prompt)
```

**Step 5: Run tests**

Run: `pytest tests/unit/test_planning.py -v`
Expected: All 5 tests PASS

**Step 6: Commit**

```bash
git add weebot/flow/__init__.py weebot/flow/planning.py tests/unit/test_planning.py
git commit -m "feat: add PlanningTool and PlanningFlow for multi-step agent orchestration"
```

---

## Task 9: Full Verification

**Step 1: Run all tests**

Run: `pytest tests/ -q`
Expected: All tests PASS, 0 failures

**Step 2: Verify no broken imports**

Run: `python -c "from weebot.tools.base import BaseTool, ToolCollection; print('base OK')"`
Run: `python -c "from weebot.core.tool_agent import ToolCallWeebotAgent; print('agent OK')"`
Run: `python -c "from weebot.flow.planning import PlanningFlow; print('flow OK')"`
Run: `python -c "from weebot.tools.web_search import WebSearchTool; print('search OK')"`
Run: `python -c "from weebot.tools.file_editor import StrReplaceEditorTool; print('editor OK')"`
Run: `python -c "from weebot.tools.control import AskHumanTool, TerminateTool; print('control OK')"`

Expected: All print OK

**Step 3: Update plan progress tracker**

Update `docs/plans/2026-02-28-openclaw-features.md` — mark Tasks 2, 3, 4 as ✅

Update `docs/plans/2026-02-28-weebot-refactor.md` — mark Tasks 3, 4, 5, 8 as ✅

**Step 4: Update MEMORY.md**

Add to pending tasks: OpenClaw Tasks 5-9 still pending (ExecApprovalPolicy, Sub-sessions, Activity stream, Reconnect backoff, System tray)
Add to completed: OpenManus integration Tasks 1-8

**Step 5: Final commit**

```bash
git add -A
git commit -m "docs: update progress trackers after OpenManus integration"
```
