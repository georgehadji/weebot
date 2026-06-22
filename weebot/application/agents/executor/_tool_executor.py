"""ToolExecutor — isolated tool dispatch for ExecutorAgent.

Responsible for executing individual tool calls and batches, managing
pre/post hooks, timeouts, and end-of-step summarization.  Extracted
from the original ExecutorAgent god class.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
from collections import deque

from weebot.application.models.tool_collection import ToolCollection
from weebot.application.services.tool_call_repair import repair_json_string
from weebot.config.constants import TEMPERATURE_BALANCED
from weebot.domain.models.event import AgentEvent, MessageEvent
from weebot.domain.models.session import Session
from weebot.domain.models.plan import Step
from weebot.tools.base import ToolResult

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tool calls with pre/post hooks, timeouts, and batching.

    Receives its dependencies via constructor so ExecutorAgent stays
    focused on step orchestration.
    """

    def __init__(
        self,
        tools: ToolCollection,
        hooks=None,  # HookRegistryPort | None
        conversation_buffer: deque | None = None,
        system_prompt: str | None = None,
        llm=None,  # LLMPort
        model: str | None = None,
    ) -> None:
        self._tools = tools
        self._hooks = hooks
        self._conversation_buffer = conversation_buffer or deque(maxlen=15)
        self._system_prompt = system_prompt
        self._llm = llm
        self._model = model
        self._current_step_id: str = ""
        self._current_session_id: str = ""

    # ── Dynamic context ────────────────────────────────────────────

    def set_step_context(self, step_id: str, session_id: str) -> None:
        """Update the current step/session context (called at step start)."""
        self._current_step_id = step_id
        self._current_session_id = session_id

    def _get_step_id(self) -> str:
        return self._current_step_id or "unknown"

    # ── Batch execution ────────────────────────────────────────────

    async def execute_tool_batch(
        self, tool_calls: list[dict],
    ) -> list[ToolResult]:
        """Execute tool calls concurrently; return results in declared order.

        Per-tool concurrency capping (``max_concurrent``) is enforced by
        ``ToolCollection.execute()`` via its per-tool semaphore registry.
        One failure does not cancel the batch — error results are placed
        in the correct slot.
        """
        if not tool_calls:
            return []
        tasks: list[asyncio.Task[ToolResult]] = []
        for tc in tool_calls:
            tasks.append(asyncio.ensure_future(self._execute_single_tool_call(tc)))
        return await asyncio.gather(*tasks)

    # ── Single tool execution ──────────────────────────────────────

    async def execute_tool(
        self, name: str, arguments: str | dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a single tool call by name and arguments.

        Handles JSON argument parsing, pre/post hooks, and timeout.
        """
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
                if not isinstance(args, dict):
                    return ToolResult.error_result(
                        error=f"Invalid tool arguments JSON for '{name}': expected object.",
                        output=f"Invalid tool arguments JSON for '{name}'.",
                        tool_name=name,
                    )
            except json.JSONDecodeError:
                # Attempt repair before giving up
                repaired = repair_json_string(arguments)
                if repaired is not None:
                    try:
                        args = json.loads(repaired)
                        if not isinstance(args, dict):
                            return ToolResult.error_result(
                                error=f"Invalid tool arguments JSON for '{name}': expected object.",
                                output=f"Invalid tool arguments JSON for '{name}'.",
                                tool_name=name,
                            )
                    except json.JSONDecodeError:
                        return ToolResult.error_result(
                            error=f"Invalid tool arguments JSON for '{name}': unrepairable.",
                            output=f"Invalid tool arguments JSON for '{name}'.",
                            tool_name=name,
                        )
                else:
                    return ToolResult.error_result(
                        error=f"Invalid tool arguments JSON for '{name}': unrepairable.",
                        output=f"Invalid tool arguments JSON for '{name}'.",
                        tool_name=name,
                    )
        else:
            args = arguments or {}

        # Determine effective timeout
        tool_obj = self._tools.get_tool(name)
        timeout = float(getattr(tool_obj, "default_timeout_seconds", 60) if tool_obj else 60)
        if "timeout" in args:
            try:
                timeout = min(float(args["timeout"]) + 5.0, 305.0)
            except (ValueError, TypeError):
                pass

        # Pre-tool hook
        if self._hooks is not None:
            await self._hooks.execute_hooks("pre_tool_call", {
                "session_id": self._current_session_id,
                "step_id": self._get_step_id(),
                "tool_name": name,
                "tool_args": args,
            })

        import time as _timer
        _t0 = _timer.monotonic()
        try:
            result = await asyncio.wait_for(
                self._tools.execute(_name=name, **args), timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Tool %s timed out after %.0fs", name, timeout)
            return ToolResult.error_result(
                error=f"Tool '{name}' timed out after {int(timeout)}s.",
                output=f"Tool '{name}' timed out after {int(timeout)}s.",
                timeout_seconds=timeout,
                tool_name=name,
            )
        _elapsed = (_timer.monotonic() - _t0) * 1000

        # Post-tool hook
        if self._hooks is not None:
            await self._hooks.execute_hooks("post_tool_call", {
                "session_id": self._current_session_id,
                "step_id": self._get_step_id(),
                "tool_name": name,
                "tool_args": args,
                "result": result,
                "elapsed_ms": _elapsed,
                "success": not isinstance(result, Exception),
            })
        return result

    async def _execute_single_tool_call(self, tc: Dict[str, Any]) -> ToolResult:
        """Thin wrapper: parse tool call dict and delegate to execute_tool."""
        return await self.execute_tool(
            tc["function"]["name"], tc["function"].get("arguments", "{}"),
        )

    # ── Summarization ──────────────────────────────────────────────

    async def summarize(self) -> AsyncGenerator[AgentEvent, None]:
        """Produce an end-of-step LLM summary from the conversation buffer."""
        has_error = any(
            (msg.get("role") == "assistant" and "error" in str(msg.get("content", "")).lower())
            for msg in self._conversation_buffer
        )
        summary_prompt = (
            "Provide a concise summary of what was accomplished, what failed, "
            "and concrete next steps for the user."
            if has_error
            else "Provide a concise summary of what was accomplished."
        )
        self._conversation_buffer.append({
            "role": "user",
            "content": summary_prompt,
        })
        system_prompt = self._system_prompt or _load_executor_system_prompt()
        messages = [{"role": "system", "content": system_prompt}] + list(self._conversation_buffer)
        response = await self._llm.chat(
            messages=messages,
            model=self._model,
            temperature=TEMPERATURE_BALANCED,
        )
        yield MessageEvent(role="assistant", message=response.content or "Done.")


def _load_executor_system_prompt() -> str:
    """Load the executor system prompt from package or inline fallback."""
    import importlib.resources as pkg_resources
    try:
        return pkg_resources.read_text("weebot.config", "executor_system_prompt.txt")
    except Exception:
        return _EXECUTOR_SYSTEM_PROMPT_FALLBACK


_EXECUTOR_SYSTEM_PROMPT_FALLBACK = """You are an execution agent. You have access to tools.
Follow the plan step by step. Execute each step before moving to the next.
When you complete all steps, report back to the user."""
