"""ToolCallWeebotAgent — ReAct loop with OpenAI function calling."""
from __future__ import annotations
import asyncio
import json
import os
from typing import Any

from openai import AsyncOpenAI

from weebot.tools.base import ToolCollection, ToolResult
from weebot.domain.models import (
    AgentState, Memory, Message, Role, ToolCallSpec,
)
from weebot.utils.cost_ledger import CostLedger

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
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "no-key"
        base_url = None
        if not os.getenv("OPENAI_API_KEY") and os.getenv("DEEPSEEK_API_KEY"):
            base_url = "https://api.deepseek.com"

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model or os.getenv("WEEBOT_MODEL", "gpt-4o-mini")
        self.tools = tools
        self.max_steps = max_steps
        self.memory = Memory()
        self.state = AgentState.IDLE
        self._ledger = CostLedger()
        self._step_count = 0

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

        self._step_count += 1
        response = await self._client.chat.completions.create(**kwargs)

        # Capture exact token counts from the API response and display EUR cost.
        if getattr(response, "usage", None) is not None:
            cost = self._ledger.record(
                step=f"step-{self._step_count}",
                usage=response.usage,
                model=self.model,
            )
            self._ledger.print_step(cost)

        msg = response.choices[0].message

        tool_calls: list[ToolCallSpec] = []
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
        """Execute tool calls from the last assistant message in parallel."""
        last = self.memory.messages[-1]

        async def _run_one(tc: ToolCallSpec) -> tuple[str, ToolResult]:
            try:
                args = json.loads(tc.arguments)
            except json.JSONDecodeError:
                args = {}
            return tc.id, await self.tools.execute(tc.name, **args)

        pairs = await asyncio.gather(*[_run_one(tc) for tc in last.tool_calls])
        for tc_id, result in pairs:
            self.memory.add(Message(
                role=Role.TOOL,
                content=str(result),
                tool_call_id=tc_id,
            ))

    async def run(self, prompt: str) -> str:
        """Run agent until finished or max_steps reached."""
        self.state = AgentState.RUNNING
        self.memory.add(Message.user(prompt))

        for _ in range(self.max_steps):
            has_tool_calls = await self.think()
            if not has_tool_calls:
                self.state = AgentState.FINISHED
                self._ledger.print_report()
                return self.memory.messages[-1].content or ""
            await self.act()

        self.state = AgentState.FINISHED
        self._ledger.print_report()
        return "Max steps reached without a final answer."

    @property
    def ledger(self) -> CostLedger:
        """Access the cost ledger after a run (e.g. to read total_cost_eur)."""
        return self._ledger
