"""Execution agent — executes a single step using available tools."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from typing import Any, AsyncGenerator, Dict, List, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.event import (
    AgentEvent,
    ErrorEvent,
    MessageEvent,
    StepEvent,
    StepStatus,
    ThoughtEvent,
    ToolEvent,
    ToolStatus,
    WaitForUserEvent,
)
from weebot.domain.models.plan import Plan, Step
from weebot.tools.base import ToolCollection, ToolResult

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM_PROMPT = """You are an execution agent. You have access to tools.
Your job is to execute ONE step from a larger plan. Do not try to complete the entire task in one go.

IMPORTANT RULES:
1. Use tools to execute the CURRENT step only
2. Do NOT call 'terminate' after completing just one step - only call it when the ENTIRE task is finished
3. Ask for human input ONLY when you genuinely need missing information and use the ask_human tool for that
4. Never ask follow-up questions as plain assistant text when a pause/resume is required

TOOL SELECTION GUIDELINES:
- For DATA RETRIEVAL (weather, facts, prices, news, definitions), use LIGHTWEIGHT tools FIRST:
  * weather → weather/forecast data (fast, no browser needed)
  * web_search → find information, URLs, or quick facts
  * bash (curl) → call APIs directly
- Use advanced_browser ONLY when you need to:
  * Interact with a page (click, fill forms, scroll)
  * Extract JavaScript-rendered content that web_search can't get
  * Take screenshots after navigating
- Do NOT open the browser just to read text you could get from web_search
- If a lightweight tool gets what you need, stop — don't also open the browser

EFFICIENCY:
- Aim to complete each step in 5 tool calls or fewer
- Don't repeat the same tool call with the same arguments — if it didn't work, try a DIFFERENT approach
- If you've taken 10+ tool calls on one step, something is wrong — summarize what you found and move on

You will be called repeatedly for each step. Focus only on the current step and wait for the next one.
"""


class ExecutorAgent:
    """Agent responsible for executing individual plan steps."""

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        max_steps: int = 25,
        skill_prompt: Optional[str] = None,
        max_context_turns: int = 15,
    ):
        self._llm = llm
        self._tools = tools
        self._event_bus = event_bus
        self._model = model
        self._max_steps = max_steps
        self._skill_prompt = skill_prompt
        self._max_context_turns = max_context_turns
        self._system_prompt: Optional[str] = None
        self._conversation_buffer: deque[Dict[str, Any]] = deque(maxlen=max_context_turns)
        self._facts: Dict[str, Any] = {}
        self._should_terminate = False

    @property
    def should_terminate(self) -> bool:
        """Return True if the terminate tool was called."""
        return self._should_terminate

    async def _emit(self, event: AgentEvent) -> None:
        if self._event_bus:
            await self._event_bus.publish(event)

    @property
    def facts(self) -> Dict[str, Any]:
        return dict(self._facts)

    def clear_facts(self) -> None:
        self._facts.clear()

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip().lower()

    @staticmethod
    def _tool_signature(tool_name: str, raw_arguments: str) -> str:
        try:
            parsed = json.loads(raw_arguments)
        except Exception:
            parsed = raw_arguments
        return f"{tool_name}:{json.dumps(parsed, sort_keys=True, ensure_ascii=False)}"

    @staticmethod
    def _follow_up_like(text: str) -> bool:
        lower_result = (text or "").lower()
        return any(phrase in lower_result for phrase in (
            "follow-up question",
            "follow up question",
            "do you have any follow-up questions",
            "do you have any follow up questions",
            "would you like me to proceed",
        ))

    @staticmethod
    def _parse_args_for_event(raw_arguments: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_arguments)
            return parsed if isinstance(parsed, dict) else {"_value": parsed}
        except Exception:
            return {"_raw": raw_arguments}

    @staticmethod
    def _build_stuck_error(
        step: Step,
        reason: str,
        recent_signatures: deque[str],
        max_steps: int,
    ) -> str:
        recent = list(recent_signatures)[-3:]
        recent_block = " | ".join(recent) if recent else "none"
        return (
            f"Step '{step.id}' ('{step.description}') got stuck: {reason}. "
            f"Recent tool calls: {recent_block}. "
            f"Guardrails triggered before/at max step budget ({max_steps}). "
            "Recovery: flow should replan this step or request missing user input."
        )

    async def execute_step(
        self, plan: Plan, step: Step, user_input: str | None = None
    ) -> AsyncGenerator[AgentEvent, None]:
        self._facts.clear()
        self._should_terminate = False
        self._conversation_buffer.clear()
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

        system_prompt = EXECUTOR_SYSTEM_PROMPT
        if self._skill_prompt:
            system_prompt = f"{EXECUTOR_SYSTEM_PROMPT}\n\n{self._skill_prompt}"
        self._system_prompt = system_prompt

        if not self._conversation_buffer:
            self._conversation_buffer.append({
                "role": "user",
                "content": f"Plan: {plan.title}\nStep: {step.description}\nExecute this step using available tools.",
            })
            # If this is a resume (user provided input), inject it so the LLM
            # sees the answer instead of calling ask_human again.
            if user_input:
                self._conversation_buffer.append({
                    "role": "user",
                    "content": user_input,
                })
        else:
            self._conversation_buffer.append({
                "role": "user",
                "content": f"Next step: {step.description}",
            })

        step_result = ""
        loop_error: Optional[str] = None
        repeated_assistant_turns = 0
        last_assistant_text = ""
        repeated_tool_calls = 0
        last_tool_signature: Optional[str] = None
        recent_tool_signatures: deque[str] = deque(maxlen=6)
        thought_iteration: int = 0

        for _ in range(self._max_steps):
            messages = [{"role": "system", "content": self._system_prompt}] + list(self._conversation_buffer)
            response = await self._llm.chat(
                messages=messages,
                tools=self._tools.to_params(),
                tool_choice="auto",
                model=self._model,
                temperature=0.2,
            )

            assistant_content = response.content or ""
            assistant_msg: dict = {"role": "assistant", "content": assistant_content}
            if response.tool_calls:
                assistant_msg["tool_calls"] = response.tool_calls
            self._conversation_buffer.append(assistant_msg)

            # Emit reasoning as a ThoughtEvent so consumers (CLI, WebSocket) see
            # the agent's thinking before each action.
            if assistant_content.strip():
                thought_iteration += 1
                yield ThoughtEvent(
                    step_id=step.id,
                    thought=assistant_content.strip(),
                    iteration=thought_iteration,
                )

            if not response.tool_calls:
                normalized = self._normalize_text(assistant_content)
                if normalized and normalized == last_assistant_text:
                    repeated_assistant_turns += 1
                else:
                    repeated_assistant_turns = 0
                last_assistant_text = normalized

                step_result = assistant_content or "No result"
                if self._follow_up_like(step_result):
                    step_result = "Step completed. Continuing to the next plan step."

                if repeated_assistant_turns >= 2:
                    loop_error = self._build_stuck_error(
                        step=step,
                        reason="repeated assistant-only responses with no tool progress",
                        recent_signatures=recent_tool_signatures,
                        max_steps=self._max_steps,
                    )
                    yield ErrorEvent(error=loop_error)
                    break

                yield MessageEvent(role="assistant", message=step_result)
                break

            abort_step = False
            for tc in response.tool_calls:
                tool_name = tc["function"]["name"]
                raw_arguments = tc["function"].get("arguments", "{}")
                signature = self._tool_signature(tool_name, raw_arguments)
                recent_tool_signatures.append(signature)

                if signature == last_tool_signature:
                    repeated_tool_calls += 1
                else:
                    repeated_tool_calls = 1
                    last_tool_signature = signature

                if repeated_tool_calls >= 4:
                    loop_error = self._build_stuck_error(
                        step=step,
                        reason=f"repeated identical tool call '{tool_name}'",
                        recent_signatures=recent_tool_signatures,
                        max_steps=self._max_steps,
                    )
                    yield ErrorEvent(error=loop_error)
                    abort_step = True
                    break

                event_args = self._parse_args_for_event(raw_arguments)
                yield ToolEvent(
                    tool_call_id=tc["id"],
                    tool_name=tool_name,
                    function_name=tool_name,
                    function_args=event_args,
                    status=ToolStatus.CALLING,
                )

                result = await self._execute_tool_call(tc)

                yield ToolEvent(
                    tool_call_id=tc["id"],
                    tool_name=tool_name,
                    function_name=tool_name,
                    function_args=event_args,
                    status=ToolStatus.CALLED,
                    result=str(result),
                )

                if result.data:
                    self._facts[tool_name] = result.data

                    if result.data.get("awaiting_human"):
                        question = result.data.get("question", "")
                        yield WaitForUserEvent(question=question)
                        return

                if tool_name == "terminate":
                    logger.info("Terminate tool called, task completed")
                    self._should_terminate = True
                    step_result = result.output or "Task completed"
                    yield MessageEvent(role="assistant", message=step_result)
                    abort_step = True
                    break

                self._conversation_buffer.append({
                    "role": "tool",
                    "content": str(result),
                    "tool_call_id": tc["id"],
                })

            if abort_step:
                break
        else:
            loop_error = self._build_stuck_error(
                step=step,
                reason="max step budget reached",
                recent_signatures=recent_tool_signatures,
                max_steps=self._max_steps,
            )
            yield ErrorEvent(error=loop_error)

        if loop_error:
            # Yield a terminal step event so event-stream consumers see
            # the step's final state before the generator exits.
            yield StepEvent(
                step_id=step.id,
                description=step.description,
                status=StepStatus.FAILED,
            )
            return

        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.COMPLETED)

    async def execute_tool(self, name: str, arguments: str | dict[str, Any] | None = None) -> ToolResult:
        """Public helper to execute a single tool call."""
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
                if not isinstance(args, dict):
                    return ToolResult.error_result(
                        error=f"Invalid tool arguments JSON for '{name}': expected object.",
                        output=f"Invalid tool arguments JSON for '{name}'.",
                        tool_name=name,
                    )
            except json.JSONDecodeError as exc:
                return ToolResult.error_result(
                    error=f"Invalid tool arguments JSON for '{name}': {exc.msg}.",
                    output=f"Invalid tool arguments JSON for '{name}'.",
                    tool_name=name,
                )
        else:
            args = arguments or {}
        timeout = 60.0
        try:
            result = await asyncio.wait_for(self._tools.execute(name, **args), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Tool %s timed out after %.0fs", name, timeout)
            return ToolResult.error_result(
                error=f"Tool '{name}' timed out after {int(timeout)}s.",
                output=f"Tool '{name}' timed out after {int(timeout)}s.",
                timeout_seconds=timeout,
                tool_name=name,
            )
        return result

    async def _execute_tool_call(self, tc: Dict[str, Any]) -> ToolResult:
        return await self.execute_tool(tc["function"]["name"], tc["function"].get("arguments", "{}"))

    async def summarize(self) -> AsyncGenerator[AgentEvent, None]:
        has_error = any(
            (msg.get("role") == "assistant" and "error" in str(msg.get("content", "")).lower())
            for msg in self._conversation_buffer
        )
        summary_prompt = (
            "Provide a concise summary of what was accomplished, what failed, and concrete next steps for the user."
            if has_error
            else "Provide a concise summary of what was accomplished."
        )
        self._conversation_buffer.append({
            "role": "user",
            "content": summary_prompt,
        })
        system_prompt = self._system_prompt or EXECUTOR_SYSTEM_PROMPT
        messages = [{"role": "system", "content": system_prompt}] + list(self._conversation_buffer)
        response = await self._llm.chat(
            messages=messages,
            model=self._model,
            temperature=0.3,
        )
        yield MessageEvent(role="assistant", message=response.content or "Done.")
