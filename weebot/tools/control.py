"""Control tools: TerminateTool (task complete signal) and AskHumanTool (HITL)."""
from __future__ import annotations
import asyncio

from weebot.tools.base import BaseTool, ToolResult


class TerminateTool(BaseTool):
    """Signals the agent that the task is complete. The agent should stop looping."""
    name: str = "terminate"
    description: str = (
        "Signal that the task is complete. Call this when you have a final answer "
        "and no more steps are needed. Provide a clear reason/summary."
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

    async def execute(self, reason: str, **_) -> ToolResult:
        return ToolResult(output=f"Task terminated: {reason}")


class AskHumanTool(BaseTool):
    """Pauses the agent to ask the human operator a question and wait for input."""
    name: str = "ask_human"
    description: str = (
        "Ask the human operator a question and wait for their response. "
        "Use when you need clarification, approval, or information you cannot find."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the human operator",
            }
        },
        "required": ["question"],
    }

    async def execute(self, question: str, **_) -> ToolResult:
        # Run blocking input() in thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None, input, f"\n[weebot asks] {question}\nYour answer: "
        )
        return ToolResult(output=answer.strip())
