"""Execution agent — executes a single step using available tools."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.hook_registry_port import HookRegistryPort
from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.application.services.conversation_compressor import ConversationCompressor
from weebot.application.services.step_budget import StepBudget
from weebot.application.services.token_budget_monitor import TokenBudgetMonitor
from weebot.config.constants import MAX_EXECUTOR_STEPS, TEMPERATURE_BALANCED
from weebot.config.model_refs import (
    MODEL_CASCADE_TIER1, MODEL_CASCADE_TIER2,
    MODEL_CASCADE_TIER3, MODEL_CASCADE_TIER4,
    MODEL_CODE_REVIEW,
)
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


def _classify_tool_error(error_output: str) -> Optional[str]:
    """Classify a tool error into a stable error-class key, or None if no match."""
    if not error_output:
        return None
    lo = error_output.lower()
    if "requires user confirmation" in lo:
        return "confirmation_required"
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
        skill_retriever=None,  # SkillRetrieverPort (Tier 1.2)
        personality=None,      # PersonalityManager (Phase 1.1)
        behavioral_learner=None,  # BehavioralLearner (Capability 5)
        prompt_variant_id: str | None = None,  # PromptRegistry variant (HyperAgents Enhancement 5)
        profile_name: str | None = None,  # SOUL.md profile (e.g. "coder", "researcher")
        agent_role: str | None = None,  # Agent role for per-role model selection
        hooks: "Optional[HookRegistryPort]" = None,  # HookRegistryPort for pre/post tool call events
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
        # Phase 6: Cross-step trajectory monitor — created once, persists across steps
        from weebot.application.services.trajectory_monitor import TrajectoryMonitor
        self._trajectory_monitor = TrajectoryMonitor()
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

    _TIER1_MODEL: str = MODEL_CASCADE_TIER1
    _TIER2_MODEL: str = MODEL_CASCADE_TIER2
    _TIER3_MODEL: str = MODEL_CASCADE_TIER3
    _TIER4_MODEL: str = MODEL_CASCADE_TIER4
    _REVIEW_MODEL: str = MODEL_CODE_REVIEW

    # ── Task-model routing ─────────────────────────────────────────
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
        """Per-role cascade: role-primary → role-fallback1 → role-fallback2 → tier3 → tier4.

        Priority:
        1. Role cascade (per ``get_model_cascade_for_role()``) — 3 models tailored to agent role
        2. Task-specific model (per ``_model_for_step()``) — parallel candidate
        3. Remaining cascade tiers: tier3 → tier4
        """
        is_review = self._is_review_step(description)
        tier2_model = self._REVIEW_MODEL if is_review else self._TIER2_MODEL

        # ── Per-role model cascade (primary + 2 fallbacks) ──────────
        from weebot.config.model_refs import get_model_cascade_for_role
        role_cascade = get_model_cascade_for_role(self._agent_role)
        role_primary = role_cascade[0]
        role_fallback1 = role_cascade[1] if len(role_cascade) > 1 else self._TIER2_MODEL
        role_fallback2 = role_cascade[2] if len(role_cascade) > 2 else self._TIER3_MODEL

        task_model = self._model_for_step(description)

        # ── Circuit breaker: skip models that failed 3+ times this session ──
        if not hasattr(self, "_circuit_breaker_failures"):
            self._circuit_breaker_failures: dict[str, int] = {}
        _cb = self._circuit_breaker_failures

        def _is_tripped(model_id: str) -> bool:
            return _cb.get(model_id, 0) >= 5

        def _record_failure(model_id: str) -> None:
            _cb[model_id] = _cb.get(model_id, 0) + 1
            if _cb[model_id] >= 3:
                logger.warning("Circuit breaker tripped for %s", model_id)

        # First-error tracking per model for diagnostics (Fix 8)
        _first_error: dict[str, str] = {}

        # ── Fast-fail detection ─────────────────────────────────────
        # If any model returns 404/401/403, the API key or credits are
        # likely the problem — reduce timeouts for remaining models to
        # avoid wasting 60-90s per model.
        _fast_fail_detected: bool = False

        @staticmethod
        def _is_fast_fail_error(exc: Exception) -> bool:
            """Return True if *exc* indicates an auth or not-found error."""
            msg = str(exc).lower()
            return any(kw in msg for kw in (
                "404", "401", "403", "not found", "unauthorized",
                "permission denied", "invalid api key", "resource_not_found",
            ))

        # ── Single chat helper with tiered timeout ──────────────────
        async def _try_chat(model_id: str, timeout: float = 15.0) -> LLMResponse | None:
            nonlocal _fast_fail_detected
            if _is_tripped(model_id):
                return None
            # If fast-fail was already detected, cap timeout at 15s
            effective_timeout = min(timeout, 15.0) if _fast_fail_detected else timeout
            try:
                resp = await asyncio.wait_for(
                    self._llm.chat(
                        messages=messages,
                        tools=self._tools.to_params(),
                        tool_choice="auto",
                        model=model_id,
                        temperature=TEMPERATURE_BALANCED,
                    ),
                    timeout=effective_timeout,
                )
                if resp and (resp.content or resp.tool_calls):
                    # Success — reset failure counter for this model
                    _cb[model_id] = 0
                    return resp
                # Empty response but no exception — don't count as failure
                return None
            except asyncio.TimeoutError:
                logger.debug("Model %s timed out (%.1fs) — retrying", model_id, effective_timeout)
                return None
            except Exception as exc:
                if isinstance(exc, Exception) and ErrorClassifier.should_fail_fast(exc):
                    raise
                # Detect fast-fail on first such error
                if not _fast_fail_detected and _is_fast_fail_error(exc):
                    _fast_fail_detected = True
                    logger.warning(
                        "Fast-fail detected (%s on %s) — reducing remaining cascade timeouts to 15s",
                        type(exc).__name__, model_id,
                    )
                if model_id not in _first_error:
                    err_detail = str(exc)[:300] if str(exc) else type(exc).__name__
                    _first_error[model_id] = err_detail
                    logger.warning("Model %s first error: %s", model_id, err_detail)
                else:
                    logger.debug("Model %s failed (%.1fs timeout): %s", model_id, effective_timeout, exc)
                _record_failure(model_id)
                return None

        # ── Phase 1: fire role-primary + role-fallback1 + task-model in parallel (90s) ──
        # Thinking models (Kimi, DeepSeek, GLM) need 60-90s for tool-use turns.
        # If fast-fail was already triggered, these are capped to 15s internally.
        parallel_models: list[str] = []
        for m in (role_primary, task_model, role_fallback1):
            if m and m not in parallel_models:
                parallel_models.append(m)

        tasks = {asyncio.ensure_future(_try_chat(m, timeout=90.0)): m for m in parallel_models}
        if tasks:
            done, _pending = await asyncio.wait(
                tasks.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            for fut in done:
                resp = fut.result()
                if resp is not None:
                    for pending_fut in _pending:
                        pending_fut.cancel()
                    # ── Silently retrieve exceptions from cancelled tasks ──
                    # If a pending task raised before being cancelled, its
                    # exception is "never retrieved" and Python logs a noisy
                    # warning.  Calling .exception() on each cancelled future
                    # suppresses that warning without losing diagnostic info.
                    for pfut in _pending:
                        if pfut.cancelled():
                            continue
                        try:
                            exc = pfut.exception()
                        except asyncio.InvalidStateError:
                            # Task hasn't completed yet — skip
                            continue
                        if exc is not None:
                            logger.debug(
                                "Suppressed exception from cancelled cascade task: %s",
                                exc,
                            )
                    await self._track_usage_and_maybe_compress(resp)
                    return resp

        # ── Phase 2: sequential — role-fallback2 → tier4 (60s timeout) ──
        # If fast-fail was detected, these are capped to 15s internally.
        remaining = [m for m in (role_fallback2, self._TIER4_MODEL)
                     if m and not _is_tripped(m) and m not in parallel_models]
        for model_id in remaining:
            resp = await _try_chat(model_id, timeout=60.0)
            if resp is not None:
                await self._track_usage_and_maybe_compress(resp)
                return resp

        # ── Live model refresh fallback (all-404 rescue) ──────────
        # If every model returned 404/not-found, the model IDs may be stale.
        # Try fetching current free models from OpenRouter as a last resort.
        if _fast_fail_detected and _first_error and all(
            any(kw in (err or "").lower() for kw in ("404", "not found"))
            for err in _first_error.values()
        ):
            rescue_model = await _try_live_model_rescue(messages)
            if rescue_model is not None:
                await self._track_usage_and_maybe_compress(rescue_model)
                return rescue_model

        # ── All models tripped — raise terminal error ──
        raise AllModelsTrippedError(
            f"All models in the cascade have tripped their circuit breakers. "
            f"Check OpenRouter credits at https://openrouter.ai/credits"
        )

    @staticmethod
    async def _try_live_model_rescue(
        messages: List[Dict[str, Any]],
    ) -> LLMResponse | None:
        """Last-resort: fetch current free models from OpenRouter and try the first.

        Called when ALL configured models return 404 — the model IDs may be
        globally stale.  Fetches from the OpenRouter API with a short timeout
        to avoid blocking the cascade further.

        Returns:
            An ``LLMResponse`` if a live model responds, or ``None``.
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://openrouter.ai/api/v1/models")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Live model rescue: failed to fetch model list: %s", exc)
            return None

        # Prefer free models with tool support, sorted by context length desc
        free_models: list[dict] = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if ":free" not in mid:
                continue
            params = m.get("supported_parameters", [])
            if "tools" not in params:
                continue
            ctx = m.get("context_length", 0)
            free_models.append({"id": mid, "ctx": ctx})

        if not free_models:
            # Fall back to any free model even without tool support
            for m in data.get("data", []):
                if ":free" in m.get("id", ""):
                    free_models.append({"id": m["id"], "ctx": m.get("context_length", 0)})

        if not free_models:
            logger.warning("Live model rescue: no free models found in OpenRouter listing")
            return None

        # Sort by context length descending — bigger context = more capable
        free_models.sort(key=lambda m: m["ctx"], reverse=True)
        rescue_id = free_models[0]["id"]
        logger.warning(
            "Live model rescue: trying %s (from %d live free models)",
            rescue_id, len(free_models),
        )

        try:
            from weebot.application.di import Container
            from weebot.application.ports.llm_port import LLMPort
            c = Container()
            c.configure_defaults()
            llm = c.get(LLMPort)
            resp = await asyncio.wait_for(
                llm.chat(
                    messages=messages,
                    model=rescue_id,
                    temperature=TEMPERATURE_BALANCED,
                ),
                timeout=30.0,
            )
            if resp and (resp.content or resp.tool_calls):
                logger.info("Live model rescue SUCCESS with %s", rescue_id)
                return resp
        except Exception as exc:
            logger.warning("Live model rescue failed with %s: %s", rescue_id, exc)

        return None

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
        ) + system_prompt

        if self._skill_prompt:
            system_prompt = f"{system_prompt}\n\n{self._skill_prompt}"

        # ── Tier 1.2: BM25 Skill Retrieval — inject relevant skills ──
        if self._skill_retriever is not None:
            try:
                matches = await self._skill_retriever.retrieve(
                    step.description, top_k=2
                )
                for m in matches:
                    if m.score > 0.15:  # Only inject meaningfully relevant skills
                        system_prompt += (
                            f"\n\n## Relevant Skill: {m.skill_name}\n"
                            f"{m.content_preview}"
                        )
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

        # ── Tier 1.3: TrajectoryMonitor — reset per-step windows, preserve cross-step ──
        if self._trajectory_monitor is not None:
            self._trajectory_monitor.reset_step()

        self._step_budget.reset()
        while self._step_budget.consume():
            messages = [{"role": "system", "content": self._system_prompt}] + list(self._conversation_buffer)
            # Cost cascade: try budget model first, fall back to primary on failure.
            try:
                response = await self._call_with_cascade(messages, description=step.description)
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
            # ── Phase 2: Pre-flight checks (sequential) ─────────
            # Check for repeated tool signatures before executing
            # anything, so we don't waste parallel execution on a
            # stuck sequence.
            _batch_tool_calls: list[dict] = []
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
                _batch_tool_calls.append(tc)

            if abort_step:
                break

            # ── Phase 2: Execute all tool calls in parallel ─────
            results = await self._execute_tool_batch(_batch_tool_calls)

            # Guard: must have same length as input
            assert len(results) == len(_batch_tool_calls), (
                f"Mismatched result count {len(results)} vs "
                f"tool call count {len(_batch_tool_calls)}"
            )

            # ── Process results in declared order ───────────────
            for tc, result in zip(_batch_tool_calls, results):
                tool_name = tc["function"]["name"]
                raw_arguments = tc["function"].get("arguments", "{}")
                event_args = self._parse_args_for_event(raw_arguments)
                signature = self._tool_signature(tool_name, raw_arguments)
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
                    )
                    if diagnosis.recovery_message:
                        self._conversation_buffer.append({
                            "role": "system",
                            "content": f"[RECOVERY] {diagnosis.recovery_message}",
                        })
                    logger.warning(
                        "Trajectory %s for step %s: %s",
                        diagnosis.health.value, step.id, diagnosis.detail,
                    )
                    _auto_abort_health = {
                        TrajectoryHealth.TERMINAL,
                        TrajectoryHealth.SEMANTIC_LOOP,
                        TrajectoryHealth.STAGNATING,
                    }
                    if diagnosis.health in _auto_abort_health:
                        loop_error = (
                            f"Trajectory {diagnosis.health.value} for step '{step.id}': "
                            f"{diagnosis.detail}. Auto-aborting step."
                        )
                        yield ErrorEvent(error=loop_error)
                        abort_step = True
                        break

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

    # ── Phase 2: Parallel tool execution ─────────────────────────
    # Per-tool semaphore gating is handled by ToolCollection.execute().
    # The executor simply fires all tool calls concurrently via gather.

    async def _execute_tool_batch(
        self,
        tool_calls: list[dict],
    ) -> list[ToolResult]:
        """Execute tool calls concurrently; return results in declared order.

        Per-tool concurrency capping (``max_concurrent``) is enforced by
        ``ToolCollection.execute()`` via its per-tool semaphore registry.
        One failure does not cancel the batch — error results are placed
        in the correct slot.
        """
        tasks: list[asyncio.Task[ToolResult]] = []
        for tc in tool_calls:
            tasks.append(asyncio.ensure_future(self._execute_tool_call(tc)))

        raw = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[ToolResult] = []
        for i, r in enumerate(raw):
            if isinstance(r, Exception):
                tc = tool_calls[i]
                t_name = tc["function"]["name"]
                results.append(ToolResult.error_result(
                    error=f"Tool '{t_name}' raised: {r}",
                    tool_name=t_name,
                ))
            else:
                results.append(r)
        return results

    def _get_step_id(self) -> str:
        return getattr(self, '_current_step_id', 'unknown')

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
        # Determine effective timeout for the asyncio safety net.
        # Tools like bash/powershell have their own internal timeouts, but
        # this provides a hard ceiling for the awaitable itself.
        # Phase 3: Use per-tool default if available, fall back to 60s.
        tool_obj = self._tools.get_tool(name)
        timeout = float(getattr(tool_obj, "default_timeout_seconds", 60) if tool_obj else 60)
        if "timeout" in args:
            try:
                # Allow up to 300s (max) if explicitly requested
                timeout = min(float(args["timeout"]) + 5.0, 305.0)
            except (ValueError, TypeError):
                pass
        
        # Pre-tool hook
        if self._hooks is not None:
            await self._hooks.execute_hooks("pre_tool_call", {
                "session_id": getattr(self, '_current_session_id', 'unknown'),
                "step_id": self._get_step_id(),
                "tool_name": name,
                "tool_args": args,
            })
        import time as _timer
        _t0 = _timer.monotonic()
        try:
            result = await asyncio.wait_for(self._tools.execute(_name=name, **args), timeout=timeout)
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
                "session_id": getattr(self, '_current_session_id', 'unknown'),
                "step_id": self._get_step_id(),
                "tool_name": name,
                "tool_args": args,
                "result": result,
                "elapsed_ms": _elapsed,
                "success": not isinstance(result, Exception),
            })
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
        system_prompt = self._system_prompt or _load_executor_system_prompt()
        messages = [{"role": "system", "content": system_prompt}] + list(self._conversation_buffer)
        response = await self._llm.chat(
            messages=messages,
            model=self._model,
            temperature=0.3,
        )
        yield MessageEvent(role="assistant", message=response.content or "Done.")
