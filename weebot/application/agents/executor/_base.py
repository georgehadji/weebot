"""Execution agent — executes a single step using available tools."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.middleware.chain import MiddlewareChain

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.hook_registry_port import HookRegistryPort
from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.application.services.conversation_compressor import ConversationCompressor
from weebot.application.services.step_budget import StepBudget
from weebot.application.services.token_budget_monitor import TokenBudgetMonitor
from weebot.config.constants import (
    MAX_EXECUTOR_STEPS,
    MAX_TOKENS_SHORT,
    TEMPERATURE_BALANCED,
    TEMPERATURE_DETERMINISTIC,
)
from weebot.config.model_refs import (
    MODEL_CASCADE_TIER1, MODEL_CASCADE_TIER2,
    MODEL_CASCADE_TIER3, MODEL_CASCADE_TIER4,
    MODEL_CODE_REVIEW,
)
from weebot.core.error_classifier import ErrorClassifier, ErrorCategory
from weebot.application.agents.executor._error_handler import normalize_text, tool_signature, follow_up_like, parse_args_for_event, classify_tool_error, build_stuck_error
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
from weebot.domain.exceptions import AllModelsTrippedError
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.trajectory import TrajectoryHealth
from weebot.application.models.tool_collection import ToolCollection
from weebot.tools.base import ToolResult

logger = logging.getLogger(__name__)

# EXECUTOR_SYSTEM_PROMPT is loaded from weebot/config/prompts/executor_system.txt.
# An inline fallback is kept for environments where the file is not available.
_EXECUTOR_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / "executor_system.txt"

_EXECUTOR_SYSTEM_PROMPT_FALLBACK = """You are an execution agent. You have access to tools.
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


def _load_executor_system_prompt() -> str:
    """Load the executor system prompt from the package or filesystem.

    Priority: (1) importlib.resources (packaged), (2) filesystem path
    (source checkout), (3) inline fallback constant.
    """
    # 1. Try importlib.resources (works when weebot is installed as a package)
    try:
        from importlib.resources import files as _resource_files
        return _resource_files("weebot.config.prompts").joinpath("executor_system.txt").read_text(encoding="utf-8")
    except Exception:
        pass

    # 2. Try filesystem path (works in development / source checkout)
    try:
        if _EXECUTOR_SYSTEM_PROMPT_PATH.exists():
            return _EXECUTOR_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        pass

    # 3. Inline fallback — kept in sync with executor_system.txt
    return _EXECUTOR_SYSTEM_PROMPT_FALLBACK

# ── Policy-error-loop detection constants (Fix 5) ──
_MAX_SAME_ERROR_CLASS = 3


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
        skill_retriever=None,  # SkillRetrieverPort (Tier 1.2)
        personality=None,      # PersonalityManager (Phase 1.1)
        behavioral_learner=None,  # BehavioralLearner (Capability 5)
        prompt_variant_id: str | None = None,  # PromptRegistry variant (HyperAgents Enhancement 5)
        profile_name: str | None = None,  # SOUL.md profile (e.g. "coder", "researcher")
        agent_role: str | None = None,  # Agent role for per-role model selection
        hooks: "Optional[HookRegistryPort]" = None,  # HookRegistryPort for pre/post tool call events
        harness_instruction_block: str | None = None,  # Self-Harness behavioural instructions
        middleware_chain: Optional["MiddlewareChain"] = None,  # MiddlewareChain — interceptor pipeline
    ):
        self._llm = llm
        self._tools = tools
        self._event_bus = event_bus
        self._model = model
        self._max_steps = max_steps
        self._skill_prompt = skill_prompt
        self._skill_retriever = skill_retriever
        self._personality = personality
        self._profile_name = profile_name
        self._agent_role = agent_role
        self._hooks = hooks
        self._behavioral_learner = behavioral_learner
        self._prompt_variant_id = prompt_variant_id
        self._harness_instruction_block = harness_instruction_block or None
        self._middleware_chain: Optional["MiddlewareChain"] = middleware_chain
        # Phase 6: Cross-step trajectory monitor — created once, persists across steps
        from weebot.application.services.trajectory_monitor import TrajectoryMonitor
        self._trajectory_monitor = TrajectoryMonitor()
        # Phase 2: skill-gap signals collected during retrieval; processed at session end
        self._skill_gaps: list[dict] = []
        self._max_context_turns = max_context_turns
        self._system_prompt: Optional[str] = None
        self._conversation_buffer: deque[Dict[str, Any]] = deque(maxlen=max_context_turns)
        self._facts: Dict[str, Any] = {}
        self._should_terminate = False
        # Phase 2 vision reflection: last predicted outcome, fed back into the
        # next reflection so the model can self-correct (expected vs. actual).
        self._last_expected_outcome: Optional[str] = None
        # Token tracking + auto-compress
        self._auto_compress = auto_compress
        self._context_window = context_window
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._compressor: Optional[ConversationCompressor] = None
        # Thread-safe step budget
        self._step_budget = StepBudget(max_steps=max_steps)
        # Context compressor -- conversation buffer, token tracking, vision reflection
        from weebot.application.agents.executor._context_compressor import ContextCompressor
        self._context_compressor: ContextCompressor = ContextCompressor(
            conversation_buffer=self._conversation_buffer,
            auto_compress=auto_compress,
            context_window=context_window,
            llm=llm,
            model=model,
        )
        # Cascade executor -- manages per-role model cascade + circuit breakers
        from weebot.application.agents.executor._cascade import CascadeExecutor
        self._cascade: CascadeExecutor = CascadeExecutor(
            llm=llm,
            tools=tools,
            agent_role=agent_role,
            model_provider=self._model_for_step,
            on_success=self._context_compressor.track_usage_and_maybe_compress,
        )
        # Tool executor -- isolated tool dispatch with hooks, timeouts, batching
        from weebot.application.agents.executor._tool_executor import ToolExecutor
        self._tool_executor: ToolExecutor = ToolExecutor(
            tools=tools,
            hooks=hooks,
            conversation_buffer=self._conversation_buffer,
            system_prompt=self._system_prompt,
            llm=llm,
            model=model,
        )

    def set_harness_block(self, block: str | None) -> None:
        """Update the harness instruction block for the next step.

        Called between steps when model-cascade switches the active model,
        allowing model-specific instructions to be injected without
        re-creating the executor.
        """
        self._harness_instruction_block = block or None

    @property
    def should_terminate(self) -> bool:
        """Return True if the terminate tool was called."""
        return self._should_terminate

    def _load_prompt(self) -> str:
        """Load the executor system prompt, checking PromptRegistry first."""
        if self._prompt_variant_id:
            try:
                from weebot.application.services.prompt_registry import PromptRegistry
                registry = PromptRegistry()
                content = registry.get_variant(self._prompt_variant_id)
                if content and content.prompt_content:
                    return content.prompt_content
            except Exception:
                pass
        return _load_executor_system_prompt()

    async def _emit(self, event: AgentEvent) -> None:
        if self._event_bus:
            await self._event_bus.publish(event)

    @property
    def facts(self) -> Dict[str, Any]:
        return dict(self._facts)

    def clear_facts(self) -> None:
        self._facts.clear()

    @staticmethod
    def _model_for_step(description: str) -> str:
        """Return the best model for *description* using the task-model router.

        Falls back to _TIER1_MODEL if the router can't load or classify.
        """
        try:
            from weebot.application.services.task_model_router import model_for_step
            return model_for_step(description)
        except Exception:
            return MODEL_CASCADE_TIER1


    def token_usage(self) -> Dict[str, int]:
        """Cumulative real token usage for this executor instance."""
        return {
            "prompt_tokens": self._context_compressor.total_prompt_tokens,
            "completion_tokens": self._context_compressor.total_completion_tokens,
            "total_tokens": self._context_compressor.total_prompt_tokens + self._context_compressor.total_completion_tokens,
        }

    def _vision_enabled(self) -> bool:
        """True when vision-in-the-loop is on and the active model accepts images."""
        return self._context_compressor.vision_enabled

    def _inject_screenshot(self, tool_name: str, image_b64: str) -> None:
        """Forward to context compressor (kept for test compatibility)."""
        self._context_compressor.inject_screenshot(tool_name, image_b64)

    def _inject_reflection(self, reflection: "VisionReflection") -> None:
        """Forward to context compressor."""
        self._context_compressor.inject_reflection(reflection)

    async def execute_step(
        self, plan: Plan, step: Step, user_input: str | None = None,
        session_id: str = "",
    ) -> AsyncGenerator[AgentEvent, None]:
        self._facts.clear()
        self._should_terminate = False
        self._conversation_buffer.clear()
        self._current_step_id = step.id
        self._current_session_id = session_id or getattr(self, '_current_session_id', 'unknown')
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

        # ═══ Policy-error-loop tracking (Fix 5) ═══
        consecutive_error_class_counts: dict[str, int] = {}
        last_error_class: Optional[str] = None

        system_prompt = self._load_prompt()

        # ═══ BOOT: PowerShell environment reminder (before everything else) ═══
        system_prompt = (
            "CRITICAL: You are running on Windows 11 with PowerShell 5.1. "
            "ALL shell commands MUST use PowerShell-native syntax:\n"
            "  ls -la <dir>  →  Get-ChildItem <dir>\n"
            "  mkdir -p <dir> →  New-Item -ItemType Directory -Force -Path <dir>\n"
            "  rm -rf <dir>  →  Remove-Item -Recurse -Force <dir>\n"
            "  cat <file>    →  Get-Content <file>\n"
            "  && chains     →  ; (semicolons)\n"
            "  Never use Unix commands — they WILL fail.\n"
            "WORKING DIRECTORY: The working directory does NOT persist between tool calls. "
            "Always use absolute paths or chain the directory change inline: "
            "  Set-Location E:\\Output\\<project>; <command>\n"
        ) + system_prompt

        # ── Self-Harness: inject behavioural instruction block ──────
        if self._harness_instruction_block:
            system_prompt = f"{system_prompt}\n{self._harness_instruction_block}"

        if self._skill_prompt:
            system_prompt = f"{system_prompt}\n\n{self._skill_prompt}"

        # ── Tier 1.2: BM25 Skill Retrieval — inject relevant skills ──
        if self._skill_retriever is not None:
            try:
                matches = await self._skill_retriever.retrieve(
                    step.description, top_k=2
                )
                best_score = max((m.score for m in matches), default=0.0)
                for m in matches:
                    if m.score > 0.15:  # Only inject meaningfully relevant skills
                        system_prompt += (
                            f"\n\n## Relevant Skill: {m.skill_name}\n"
                            f"{m.content_preview}"
                        )
                # Phase 2: detect retrieval miss and record gap signal
                _maybe_record_skill_gap(self, step.description, best_score)
            except Exception as exc:
                logger.warning("Skill retrieval failed: %s", exc)

        # ── Capability 5: Behavioral Rules — inject learned rules ──
        if self._behavioral_learner is not None:
            try:
                rules_prompt = self._behavioral_learner.get_rules_for_prompt()
                if rules_prompt:
                    system_prompt += f"\n\n{rules_prompt}"
            except Exception as exc:
                logger.warning("Behavioral rules injection failed: %s", exc)

        # ── Phase 1.1: Core Personality — inject WEEBOT_CORE.md + SOUL.md ──
        if self._personality is not None and self._personality.loaded:
            system_prompt += self._personality.get_system_prompt(
                profile_name=self._profile_name,
            )

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
        semantic_loop_recoveries: int = 0
        _MAX_SEMANTIC_LOOP_RECOVERIES = 2

        # ── Tier 1.3: TrajectoryMonitor — reset per-step windows, preserve cross-step ──
        if self._trajectory_monitor is not None:
            self._trajectory_monitor.reset_step()

        self._step_budget.reset()
        while self._step_budget.consume():
            # ── Pre-call compaction: ensure the LLM sees compacted context ──
            await self._context_compressor._maybe_compress()

            messages = [{"role": "system", "content": self._system_prompt}] + list(self._conversation_buffer)

            # ── Middleware: before_request ──────────────────────────────────
            if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                _mw_tools = self._tools.to_params() if self._tools else []
                messages, _mw_tools = await self._middleware_chain.apply_before_request(
                    messages=messages,
                    tools=_mw_tools,
                    step_id=step.id,
                    step_description=step.description,
                )

            # Cost cascade: try budget model first, fall back to primary on failure.
            try:
                response = await self._cascade.call_with_cascade(messages, description=step.description)
            except AllModelsTrippedError as exc:
                yield ErrorEvent(error=str(exc))
                yield MessageEvent(
                    role="assistant",
                    message=(
                        "All AI models are currently unavailable. Please:\n"
                        "1. Check your OpenRouter credits at https://openrouter.ai/credits\n"
                        "2. Verify your OPENROUTER_API_KEY is valid\n"
                        "3. Wait a few minutes for circuit breakers to cool down and retry"
                    ),
                )
                break

            assistant_content = response.content or ""

            # ── Middleware: after_response ─────────────────────────────────
            if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                assistant_content, _modified_tc = await self._middleware_chain.apply_after_response(
                    content=assistant_content,
                    tool_calls=response.tool_calls or [],
                    messages=messages,
                    tools=self._tools.to_params() if self._tools else [],
                )
                if response.tool_calls:
                    response.tool_calls = _modified_tc

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
                normalized = normalize_text(assistant_content)
                if normalized and normalized == last_assistant_text:
                    repeated_assistant_turns += 1
                else:
                    repeated_assistant_turns = 0
                last_assistant_text = normalized

                step_result = assistant_content or "No result"
                if follow_up_like(step_result):
                    step_result = "Step completed. Continuing to the next plan step."

                if repeated_assistant_turns >= 2:
                    loop_error = build_stuck_error(
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
            # ── Phase 2: Pre-flight checks (sequential) ─────────
            # Check for repeated tool signatures before executing
            # anything, so we don't waste parallel execution on a
            # stuck sequence.
            _batch_tool_calls: list[dict] = []
            for tc in response.tool_calls:
                tool_name = tc["function"]["name"]
                raw_arguments = tc["function"].get("arguments", "{}")
                signature = tool_signature(tool_name, raw_arguments)
                recent_tool_signatures.append(signature)

                if signature == last_tool_signature:
                    repeated_tool_calls += 1
                else:
                    repeated_tool_calls = 1
                    last_tool_signature = signature

                if repeated_tool_calls >= 4:
                    loop_error = build_stuck_error(
                        step=step,
                        reason=f"repeated identical tool call '{tool_name}'",
                        recent_signatures=recent_tool_signatures,
                        max_steps=self._max_steps,
                    )
                    yield ErrorEvent(error=loop_error)
                    abort_step = True
                    break

                event_args = parse_args_for_event(raw_arguments)
                yield ToolEvent(
                    tool_call_id=tc["id"],
                    tool_name=tool_name,
                    function_name=tool_name,
                    function_args=event_args,
                    status=ToolStatus.CALLING,
                )
                _batch_tool_calls.append(tc)

            if abort_step:
                break

            # ── Phase 2: Execute all tool calls in parallel ─────
            results = await self._tool_executor.execute_tool_batch(_batch_tool_calls)

            # Guard: must have same length as input
            assert len(results) == len(_batch_tool_calls), (
                f"Mismatched result count {len(results)} vs "
                f"tool call count {len(_batch_tool_calls)}"
            )

            # ── Process results in declared order ───────────────
            for tc, result in zip(_batch_tool_calls, results):
                tool_name = tc["function"]["name"]
                raw_arguments = tc["function"].get("arguments", "{}")
                event_args = parse_args_for_event(raw_arguments)
                signature = tool_signature(tool_name, raw_arguments)
                tool_calls_attempted += 1
                if not result.is_error:
                    tool_calls_succeeded += 1

                # ── Tier 1.3: TrajectoryMonitor — detect degenerate patterns ──
                if self._trajectory_monitor is not None:
                    diagnosis = self._trajectory_monitor.diagnose(
                        step_id=step.id,
                        tool_signature=signature,
                        tool_output=result.output or "",
                        step_result=step_result if step_result else None,
                        total_budget=self._max_steps,
                        used_budget=tool_calls_attempted,
                        available_tools=list(self._tools._tools.keys()) if self._tools else None,
                    )
                    if diagnosis.recovery_message:
                        self._conversation_buffer.append({
                            "role": "system",
                            "content": f"[RECOVERY] {diagnosis.recovery_message}",
                        })
                    if diagnosis.health == TrajectoryHealth.HEALTHY:
                        logger.debug(
                            "Trajectory %s for step %s: %s",
                            diagnosis.health.value, step.id, diagnosis.detail,
                        )
                    else:
                        logger.warning(
                            "Trajectory %s for step %s: %s",
                            diagnosis.health.value, step.id, diagnosis.detail,
                        )
                    # Give SEMANTIC_LOOP up to 2 recovery attempts before aborting.
                    # The monitor already injected a recovery_message above.
                    if diagnosis.health == TrajectoryHealth.SEMANTIC_LOOP:
                        if semantic_loop_recoveries < _MAX_SEMANTIC_LOOP_RECOVERIES:
                            semantic_loop_recoveries += 1
                            logger.warning(
                                "SEMANTIC_LOOP for step %s — injecting recovery hint (attempt %d/%d)",
                                step.id, semantic_loop_recoveries, _MAX_SEMANTIC_LOOP_RECOVERIES,
                            )
                            continue

                    _auto_abort_health = {
                        TrajectoryHealth.TERMINAL,
                        TrajectoryHealth.STAGNATING,
                        TrajectoryHealth.EXHAUSTED,
                    }
                    if diagnosis.health in _auto_abort_health or (
                        diagnosis.health == TrajectoryHealth.SEMANTIC_LOOP
                        and semantic_loop_recoveries >= _MAX_SEMANTIC_LOOP_RECOVERIES
                    ):
                        # Enrich the abort message with policy context if the trajectory
                        # degenerated due to security blocks rather than true semantic repetition
                        security_context = ""
                        if last_error_class in ("security_blocked", "policy_denied", "confirmation_required"):
                            count = consecutive_error_class_counts.get(last_error_class, 0)
                            security_context = (
                                f" (underlying cause: {count}× consecutive '{last_error_class}' "
                                f"errors — check security_validators.py allowlists)"
                            )
                        loop_error = (
                            f"Trajectory {diagnosis.health.value} for step '{step.id}': "
                            f"{diagnosis.detail}{security_context}. Auto-aborting step."
                        )
                        yield ErrorEvent(error=loop_error)
                        abort_step = True
                        break

                # ═══ Policy-error-loop detection (Fix 5) ═══
                if result.is_error:
                    err_class = classify_tool_error(result.error or result.output or "")
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

                # ── Middleware: after_tool_call ──────────────────────────────
                if self._middleware_chain is not None and not self._middleware_chain.is_empty():
                    _mw_result = await self._middleware_chain.apply_after_tool_call(
                        tool_name=tool_name,
                        arguments=event_args,
                        output=result.output or "",
                        error=result.error,
                        is_error=result.is_error,
                    )
                    # If middleware modified the output, update the result
                    if _mw_result.output != (result.output or ""):
                        result = ToolResult(
                            output=_mw_result.output,
                            error=_mw_result.error or result.error,
                            is_error=_mw_result.is_error or result.is_error,
                            base64_image=result.base64_image,
                        )

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
                    self._step_budget.refund(self._step_budget.remaining)
                    abort_step = True
                    break

                self._conversation_buffer.append({
                    "role": "tool",
                    "content": str(result),
                    "tool_call_id": tc["id"],
                })

                # Vision-in-the-loop: let a vision-capable model SEE the screen
                # state a tool produced, instead of driving blind off DOM/OCR text.
                if getattr(result, "base64_image", None) and self._vision_enabled():
                    self._context_compressor.inject_screenshot(tool_name, result.base64_image)
                    # Phase 2: structured observe→plan reflection (extra LLM call, opt-in).
                    # Grounded in the step description so the model can judge progress.
                    reflection = await self._context_compressor.reflect_on_screenshot(
                        tool_name, result.base64_image, task_context=step.description
                    )
                    if reflection is not None:
                        self._context_compressor.inject_reflection(reflection)

            if abort_step:
                break

        if not abort_step and loop_error is None and self._step_budget.exhausted and not step_result:
            loop_error = build_stuck_error(
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
            loop_error = build_stuck_error(
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

    # ── Phase 2: Parallel tool execution ─────────────────────────
    # Per-tool semaphore gating is handled by ToolCollection.execute().
    # The executor simply fires all tool calls concurrently via gather.

# ── Phase 2 helpers ────────────────────────────────────────────────────────────


def _maybe_record_skill_gap(executor: "ExecutorAgent", step_description: str, best_score: float) -> None:
    """Record a skill-gap signal when retrieval misses the creation threshold.

    Purely additive — appends to ``executor._skill_gaps``; never raises.
    Actual IdeaContract creation and gate review happen later in CompletedState.
    """
    from weebot.config.feature_flags import SKILL_GAP_TRIGGER_ENABLED
    from weebot.config.learning import TAU_CREATE

    if not SKILL_GAP_TRIGGER_ENABLED:
        return
    if best_score >= TAU_CREATE:
        return  # retrieval hit — no gap

    executor._skill_gaps.append(
        {"step": step_description[:200], "score": best_score}
    )
    logger.debug(
        "Phase 2: skill gap recorded (score=%.3f < %.3f) for step: %s",
        best_score, TAU_CREATE, step_description[:80],
    )
