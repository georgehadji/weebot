"""Control tools: TerminateTool (task complete signal) and AskHumanTool (HITL)."""
from __future__ import annotations

from weebot.tools.base import BaseTool, ToolResult


class TerminateTool(BaseTool):
    """Signals the agent that the task is complete. The agent should stop looping."""
    name: str = "terminate"
    description: str = (
        "Signal that the task is complete. Call this ONLY when: "
        "(1) You have presented final results to the user, AND "
        "(2) The user has confirmed they have no follow-up questions. "
        "If unsure, use ask_human to check for follow-ups first."
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
        """Return a non-blocking HITL signal. The executor handles the pause."""
        return ToolResult(
            output="",
            data={"awaiting_human": True, "question": question},
            metadata={"question": question},
        )
