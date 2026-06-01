"""Execution agent — executes a single step using available tools."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from typing import Any, AsyncGenerator, Dict, List, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.application.services.conversation_compressor import ConversationCompressor
from weebot.application.services.step_budget import StepBudget
from weebot.application.services.token_budget_monitor import TokenBudgetMonitor
from weebot.config.constants import MAX_EXECUTOR_STEPS, TEMPERATURE
from weebot.config.model_refs import MODEL_BUDGET, MODEL_CASCADE_FREE, MODEL_CODE_REVIEW
from weebot.core.error_classifier import ErrorClassifier, ErrorCategory
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
from weebot.application.models.tool_collection import ToolCollection
from weebot.tools.base import ToolResult

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

POWERSHELL SYNTAX RULES (Windows 11):
- Static .NET method calls: [ClassName]::MethodName() — e.g., [Math]::Round(x, 2)
  NOT ::Round(x, 2) which is invalid syntax.
- Format-Table, Format-List, Format-Wide are DISPLAY cmdlets, not disk operations — safe to use.
- Get-ChildItem full-disk recursion (-Recurse -ErrorAction SilentlyContinue) on C:\\ takes
  several minutes; use -Depth 2 or -Depth 3 for faster partial scans, then widen if needed.
- PowerShell background jobs (Start-Job) are scoped to the current process and do NOT
  persist across separate powershell.exe invocations. Use single-call approaches instead.
- Long timeout: pass the 'timeout' parameter on the tool call (max 300s).
  Do NOT use Start-Sleep to work around the tool timeout.

EFFICIENCY:
- Aim to complete each step in 5 tool calls or fewer
- Don't repeat the same tool call with the same arguments — if it didn't work, try a DIFFERENT approach
- If you've taken 10+ tool calls on one step, something is wrong — summarize what you found and move on

You will be called repeatedly for each step. Focus only on the current step and wait for the next one.
"""

# ── Policy-error-loop detection constants (Fix 5) ──
_MAX_SAME_ERROR_CLASS = 3


def _classify_tool_error(error_output: str) -> Optional[str]:
    """Classify a tool error into a stable error-class key, or None if no match."""
    if not error_output:
        return None
    lo = error_output.lower()
    if "denied by policy" in lo or "command blocked" in lo:
        return "policy_denied"
    if "security error" in lo or ("layer" in lo and "triggered" in lo):
        return "security_blocked"
    if "timed out" in lo:
        return "timeout"
    if "access denied" in lo or "permission" in lo:
        return "permission_denied"
    return None


class ExecutorAgent:
    """Agent responsible for executing individual plan steps."""

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        max_steps: int = MAX_EXECUTOR_STEPS,
        skill_prompt: Optional[str] = None,
        max_context_turns: int = 15,
        auto_compress: bool = True,
        context_window: int = 128_000,
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
        # Token tracking + auto-compress
        self._auto_compress = auto_compress
        self._context_window = context_window
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._compressor: Optional[ConversationCompressor] = None
        # Thread-safe step budget
        self._step_budget = StepBudget(max_steps=max_steps)

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

    _BUDGET_MODEL: str = MODEL_BUDGET
    _FREE_MODEL: str = MODEL_CASCADE_FREE
    _REVIEW_MODEL: str = MODEL_CODE_REVIEW

    _REVIEW_KEYWORDS = (
        "review", "audit", "analyze code", "inspect", "critique",
        "security audit", "code quality", "refactor analysis"
    )

    def _is_review_step(self, description: str) -> bool:
        desc = description.lower()
        return any(kw in desc for kw in self._REVIEW_KEYWORDS)

    async def _track_usage_and_maybe_compress(self, resp: Any) -> None:
        """Accumulate real token usage from *resp* and trigger compression if needed."""
        if resp and resp.usage:
            self._total_prompt_tokens += resp.usage.get("prompt_tokens", 0)
            self._total_completion_tokens += resp.usage.get("completion_tokens", 0)
        await self._maybe_compress()

    async def _maybe_compress(self) -> None:
        """Summarize the middle of the conversation buffer when approaching context limit."""
        if not self._auto_compress:
            return
        total_tokens = self._total_prompt_tokens + self._total_completion_tokens
        threshold = int(self._context_window * 0.75)
        if total_tokens >= threshold and len(self._conversation_buffer) >= 10:
            logger.info(
                "Token usage %d >= threshold %d — compressing conversation buffer",
                total_tokens,
                threshold,
            )
            if self._compressor is None:
                self._compressor = ConversationCompressor(llm=self._llm)
            compressed = await self._compressor.compress(list(self._conversation_buffer))
            self._conversation_buffer.clear()
            for msg in compressed:
                self._conversation_buffer.append(msg)
            # Reset counters post-compaction to avoid immediate re-trigger
            self._total_prompt_tokens = int(self._total_prompt_tokens * 0.3)
            self._total_completion_tokens = 0

    @property
    def token_usage(self) -> Dict[str, int]:
        """Cumulative real token usage for this executor instance."""
        return {
            "prompt_tokens": self._total_prompt_tokens,
            "completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
        }

    async def _call_with_cascade(
        self, messages: List[Dict[str, Any]], description: str = ""
    ) -> LLMResponse:
        """Tiered cascade: free → budget|review → primary (on failure).
        
        Code-review steps use Claude Sonnet 4.6 (excels at critique).
        Other steps use kimi k2.6 (budget generalist).
        """
        is_review = self._is_review_step(description)
        budget_model = self._REVIEW_MODEL if is_review else self._BUDGET_MODEL

        # Attempt 1: FREE tier (no cost)
        try:
            resp = await self._llm.chat(
                messages=messages,
                tools=self._tools.to_params(),
                tool_choice="auto",
                model=self._FREE_MODEL,
                temperature=TEMPERATURE,
            )
            if resp and (resp.content or resp.tool_calls):
                await self._track_usage_and_maybe_compress(resp)
                return resp
        except Exception as exc:
            if ErrorClassifier.should_fail_fast(exc):
                raise
            logger.debug("FREE model failed (%s), trying budget tier: %s", self._FREE_MODEL, exc)

        # Attempt 2: BUDGET or REVIEW model
        try:
            resp = await self._llm.chat(
                messages=messages,
                tools=self._tools.to_params(),
                tool_choice="auto",
                model=budget_model,
                temperature=TEMPERATURE,
            )
            if resp and (resp.content or resp.tool_calls):
                await self._track_usage_and_maybe_compress(resp)
                return resp
        except Exception as exc:
            if ErrorClassifier.should_fail_fast(exc):
                raise
            logger.debug("Budget model failed (%s), falling back to primary: %s", budget_model, exc)

        # Attempt 3: PRIMARY model (always succeeds or raises)
        resp = await self._llm.chat(
            messages=messages,
            tools=self._tools.to_params(),
            tool_choice="auto",
            model=self._model,
            temperature=TEMPERATURE,
        )
        await self._track_usage_and_maybe_compress(resp)
        return resp

    async def execute_step(
        self, plan: Plan, step: Step, user_input: str | None = None
    ) -> AsyncGenerator[AgentEvent, None]:
        self._facts.clear()
        self._should_terminate = False
        self._conversation_buffer.clear()
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

        # ═══ Policy-error-loop tracking (Fix 5) ═══
        consecutive_error_class_counts: dict[str, int] = {}
        last_error_class: Optional[str] = None

        system_prompt = EXECUTOR_SYSTEM_PROMPT
        if self._skill_prompt:
            system_prompt = f"{EXECUTOR_SYSTEM_PROMPT}\n\n{self._skill_prompt}"
        self._system_prompt = system_prompt
        # Inject persistent memory snapshot (frozen at session start, preserves prefix cache)
        try:
            from weebot.tools.persistent_memory import PersistentMemoryTool
            snapshot = await PersistentMemoryTool.load_snapshot()
            if snapshot:
                self._system_prompt = self._system_prompt + "\n\n" + snapshot
        except Exception as exc:
            logger.warning("Persistent memory snapshot unavailable: %s", exc)

        if not self._conversation_buffer:
            # Build a rich context message so the LLM knows the full task,
            # how far along the plan is, and what the current step requires.
            completed_steps = [s for s in plan.steps if s.is_done()]
            pending_steps = [s for s in plan.steps if not s.is_done()]
            try:
                current_idx = plan.steps.index(step) + 1
            except ValueError:
                current_idx = len(completed_steps) + 1

            context_lines = [
                f"Overall goal: {plan.title}",
                f"Total steps: {len(plan.steps)} | Current: step {current_idx}",
            ]
            if plan.message:
                context_lines.append(f"Plan summary: {plan.message}")
            if completed_steps:
                done_summary = "; ".join(s.description for s in completed_steps[-3:])
                context_lines.append(f"Recently completed: {done_summary}")
            context_lines += [
                f"",
                f"Current step to execute: {step.description}",
                f"",
                "Use available tools to execute this specific step.",
            ]
            self._conversation_buffer.append({
                "role": "user",
                "content": "\n".join(context_lines),
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
        abort_step = False
        repeated_assistant_turns = 0
        last_assistant_text = ""
        repeated_tool_calls = 0
        last_tool_signature: Optional[str] = None
        recent_tool_signatures: deque[str] = deque(maxlen=6)
        thought_iteration: int = 0
        tool_calls_attempted: int = 0
        tool_calls_succeeded: int = 0

        self._step_budget.reset()
        while self._step_budget.consume():
            messages = [{"role": "system", "content": self._system_prompt}] + list(self._conversation_buffer)
            # Cost cascade: try budget model first, fall back to primary on failure.
            # This saves ~50x tokens on routine calls while keeping premium for
            # complex reasoning tasks.
            response = await self._call_with_cascade(messages, description=step.description)

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
                tool_calls_attempted += 1
                if not result.is_error:
                    tool_calls_succeeded += 1

                # ═══ Policy-error-loop detection (Fix 5) ═══
                if result.is_error:
                    err_class = _classify_tool_error(result.error or result.output or "")
                    if err_class:
                        if err_class == last_error_class:
                            consecutive_error_class_counts[err_class] = \
                                consecutive_error_class_counts.get(err_class, 0) + 1
                        else:
                            consecutive_error_class_counts = {err_class: 1}
                            last_error_class = err_class

                        if consecutive_error_class_counts.get(err_class, 0) >= _MAX_SAME_ERROR_CLASS:
                            loop_error = (
                                f"Step '{step.id}' is stuck: the same error class '{err_class}' "
                                f"has triggered {consecutive_error_class_counts[err_class]} consecutive times. "
                                f"Last error: {(result.error or result.output)[:300]}. "
                                "Requesting user input to unblock."
                            )
                            yield ErrorEvent(error=loop_error)
                            yield WaitForUserEvent(
                                question=(
                                    f"The agent is blocked by a '{err_class}' policy and cannot proceed "
                                    f"with step: {step.description!r}.\n"
                                    f"Last error: {(result.error or result.output)[:500]}\n\n"
                                    "Please either:\n"
                                    "  1. Rephrase the task to avoid the blocked operation, or\n"
                                    "  2. Adjust security settings if appropriate, then resume."
                                )
                            )
                            abort_step = True
                            break
                else:
                    last_error_class = None
                    consecutive_error_class_counts.clear()

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
                    # Refund remaining budget so parent flow tracks accurately
                    self._step_budget.refund(self._step_budget.remaining)
                    abort_step = True
                    break

                self._conversation_buffer.append({
                    "role": "tool",
                    "content": str(result),
                    "tool_call_id": tc["id"],
                })

            if abort_step:
                break

        if not abort_step and loop_error is None and self._step_budget.exhausted and not step_result:
            loop_error = self._build_stuck_error(
                step=step,
                reason="max step budget reached",
                recent_signatures=recent_tool_signatures,
                max_steps=self._max_steps,
            )
            yield ErrorEvent(error=loop_error)

        # Detect hollow completion: tools were attempted but none succeeded and
        # the LLM produced no substantive output.  Surface this as a failure so
        # the flow can replan rather than silently marking the step done.
        if (
            not abort_step
            and loop_error is None
            and tool_calls_attempted > 0
            and tool_calls_succeeded == 0
            and not step_result.strip()
        ):
            loop_error = self._build_stuck_error(
                step=step,
                reason="all tool calls failed and no output was produced",
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
