"""Execution agent — executes a single step using available tools."""
from __future__ import annotations

import contextlib
import logging
from collections import deque
from pathlib import Path
from typing import Any, TYPE_CHECKING
from collections.abc import AsyncGenerator

if TYPE_CHECKING:
    from weebot.application.middleware.chain import MiddlewareChain
    from weebot.models.structured_output import VisionReflection

from weebot.application.agents.executor._iteration_guard import (
    DEFAULT_MAX_CONTEXT_TURNS,
    IterationGuard,
    IterationGuardState,
)
from weebot.application.agents.executor._prompt_builder import build_executor_prompt

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.hook_registry_port import HookRegistryPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.ponytail_post_processor import PonytailPostProcessor
from weebot.application.services.step_budget import StepBudget
from weebot.config.settings import WORKSPACE_ROOT
from weebot.config.constants import (
    MAX_EXECUTOR_STEPS,
)
from weebot.config.model_refs import (
    MODEL_CASCADE_TIER1,
)
from weebot.core.trust_boundary import is_untrusted_tool, wrap_untrusted
from weebot.application.agents.executor._error_handler import (
    build_stuck_error,
    classify_tool_error,
    follow_up_like,
    is_expected_failure,
    normalize_text,
    parse_args_for_event,
    tool_signature,
)
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
from weebot.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)

def sanitize_tool_call_pairing(messages: list[dict]) -> list[dict]:
    """Drop tool/assistant messages whose counterpart is missing.

    The provider contract is symmetric: every ``role="tool"`` message must
    follow an assistant message whose ``tool_calls`` contains its
    ``tool_call_id``, and every advertised ``tool_call`` must be answered.
    Violating either is a 400, not a degraded response.

    Both halves can break here without anyone doing anything wrong. The
    conversation buffer is a bounded deque that evicts from the left, so once
    a step exceeds the window it splits assistant/tool pairs exactly at the
    boundary; ``_maybe_compress`` independently rewrites the middle of the
    buffer wholesale. Sizing the buffer to the tool budget makes eviction
    unlikely, not impossible — a long tool result can still trip compression
    mid-step — so the assembled message list is sanitized before dispatch
    rather than trusting the buffer to stay well-formed.

    Returns a new list; the input is not modified.
    """
    answered: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            answered.add(msg["tool_call_id"])

    offered: set[str] = set()
    result: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            kept = [
                tc for tc in msg["tool_calls"]
                if isinstance(tc, dict) and tc.get("id") in answered
            ]
            if len(kept) != len(msg["tool_calls"]):
                msg = {**msg, "tool_calls": kept}
                if not kept:
                    # An assistant turn with an empty tool_calls list is
                    # itself invalid; drop the key and keep the prose.
                    msg.pop("tool_calls")
            offered.update(tc["id"] for tc in kept)
            result.append(msg)
            continue
        if role == "tool":
            if msg.get("tool_call_id") not in offered:
                continue  # orphan: its parent assistant turn is gone
            result.append(msg)
            continue
        result.append(msg)
    return result

# EXECUTOR_SYSTEM_PROMPT is loaded from weebot/config/prompts/executor_system.txt.
# An inline fallback is kept for environments where the file is not available.
_EXECUTOR_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config"
    / "prompts"
    / "executor_system.txt"
)

_EXECUTOR_SYSTEM_PROMPT_FALLBACK = (
    "You are an execution agent. You have access to tools.\n"
    "Your job is to execute ONE step from a larger plan. Do not try to complete the entire task in "
    "one go.\n"
    "\n"
    "IMPORTANT RULES:\n"
    "1. Use tools to execute the CURRENT step only\n"
    "2. Do NOT call 'terminate' after completing just one step - only call it when the ENTIRE task "
    "is finished\n"
    "3. Ask for human input ONLY when you genuinely need missing information and use the ask_human "
    "tool for that\n"
    "4. Never ask follow-up questions as plain assistant text when a pause/resume is required\n"
    "\n"
    "TOOL SELECTION GUIDELINES:\n"
    "- For DATA RETRIEVAL (weather, facts, prices, news, definitions), use LIGHTWEIGHT tools "
    "FIRST:\n"
    "  * weather → weather/forecast data (fast, no browser needed)\n"
    "  * web_search → find information, URLs, or quick facts\n"
    "  * bash (curl) → call APIs directly\n"
    "- Use advanced_browser ONLY when you need to:\n"
    "  * Interact with a page (click, fill forms, scroll)\n"
    "  * Extract JavaScript-rendered content that web_search can't get\n"
    "  * Take screenshots after navigating\n"
    "- Do NOT open the browser just to read text you could get from web_search\n"
    "- If a lightweight tool gets what you need, stop — don't also open the browser\n"
    "\n"
    "POWERSHELL SYNTAX RULES (Windows 11):\n"
    "- Static .NET method calls: [ClassName]::MethodName() — e.g., [Math]::Round(x, 2)\n"
    "  NOT ::Round(x, 2) which is invalid syntax.\n"
    "- Format-Table, Format-List, Format-Wide are DISPLAY cmdlets, not disk operations — "
    "safe to use.\n"
    "- Get-ChildItem full-disk recursion (-Recurse -ErrorAction SilentlyContinue) on C:\\ takes\n"
    "  several minutes; use -Depth 2 or -Depth 3 for faster partial scans, then widen if needed.\n"
    "- PowerShell background jobs (Start-Job) are scoped to the current process and do NOT\n"
    "  persist across separate powershell.exe invocations. Use single-call approaches instead.\n"
    "- Long timeout: pass the 'timeout' parameter on the tool call (max 300s).\n"
    "  Do NOT use Start-Sleep to work around the tool timeout.\n"
    "\n"
    "EFFICIENCY:\n"
    "- Aim to complete each step in 5 tool calls or fewer\n"
    "- Don't repeat the same tool call with the same arguments — if it didn't work, try a "
    "DIFFERENT approach\n"
    "- If you've taken 10+ tool calls on one step, something is wrong — summarize what you "
    "found and move on\n"
    "\n"
    "You will be called repeatedly for each step. Focus only on the current step and wait for the "
    "next one.\n"
)


def _load_executor_system_prompt() -> str:
    """Load the executor system prompt from the package or filesystem.

    Priority: (1) importlib.resources (packaged), (2) filesystem path
    (source checkout), (3) inline fallback constant.
    """
    # 1. Try importlib.resources (works when weebot is installed as a package)
    with contextlib.suppress(Exception):
        from importlib.resources import files as _resource_files
        return _resource_files("weebot.config.prompts").joinpath(
            "executor_system.txt"
        ).read_text(encoding="utf-8")

    # 2. Try filesystem path (works in development / source checkout)
    with contextlib.suppress(Exception):
        if _EXECUTOR_SYSTEM_PROMPT_PATH.exists():
            return _EXECUTOR_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

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
        event_bus: EventBusPort | None = None,
        model: str | None = None,
        max_steps: int = MAX_EXECUTOR_STEPS,
        skill_prompt: str | None = None,
        max_context_turns: int = DEFAULT_MAX_CONTEXT_TURNS,
        auto_compress: bool = True,
        context_window: int = 128_000,
        skill_retriever=None,  # SkillRetrieverPort (Tier 1.2)
        personality=None,      # PersonalityManager (Phase 1.1)
        behavioral_learner=None,  # BehavioralLearner (Capability 5)
        prompt_variant_id: str | None = None,  # PromptRegistry variant (HyperAgents Enhancement 5)
        profile_name: str | None = None,  # SOUL.md profile (e.g. "coder", "researcher")
        agent_role: str | None = None,  # Agent role for per-role model selection
        hooks: HookRegistryPort | None = None,  # HookRegistryPort for pre/post tool call events
        harness_instruction_block: str | None = None,  # Self-Harness behavioural instructions
        middleware_chain: MiddlewareChain | None = None,  # MiddlewareChain — interceptor pipeline
        state_repo: StateRepositoryPort | None = None,  # State repository for user profile etc.
        tracing_port: Any | None = None,  # TracingPort — OTEL distributed tracing (ARCH-AUDIT-V2 B2)
        trajectory_config: Any | None = None,  # TrajectoryConfig — Trajectory Regulation Layer (Tier 1.3)
        session_constraints: str | None = None,  # Pre-rendered SessionConstraintRegistry.render()
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
        self._middleware_chain: MiddlewareChain | None = middleware_chain
        self._state_repo: StateRepositoryPort | None = state_repo
        self._tracing_port: Any | None = tracing_port
        self._session_constraints_block: str | None = session_constraints or None
        # Phase 6: Cross-step trajectory monitor — created once, persists across steps
        from weebot.application.services.trajectory_monitor import TrajectoryMonitor
        if trajectory_config is not None:
            self._trajectory_monitor = TrajectoryMonitor(
                repetition_threshold=trajectory_config.repetition_threshold,
                stagnation_window=trajectory_config.stagnation_window,
                budget_hotspot_ratio=trajectory_config.budget_hotspot_ratio,
                exhaustion_ratio=trajectory_config.exhaustion_ratio,
            )
        else:
            self._trajectory_monitor = TrajectoryMonitor()
        # Phase 2: skill-gap signals collected during retrieval; processed at session end
        self._skill_gaps: list[dict] = []
        self._max_context_turns = max_context_turns
        self._system_prompt: str | None = None
        self._conversation_buffer: deque[dict[str, Any]] = deque(maxlen=max_context_turns)
        self._facts: dict[str, Any] = {}
        self._should_terminate = False
        # Token tracking + auto-compress
        self._auto_compress = auto_compress
        self._context_window = context_window
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
        from weebot.core.model_cascade_tracker import ModelCascadeTracker
        self._cascade: CascadeExecutor = CascadeExecutor(
            llm=llm,
            tools=tools,
            agent_role=agent_role,
            model_provider=self._resolve_model_for_step,
            on_success=self._context_compressor.track_usage_and_maybe_compress,
            tracker=ModelCascadeTracker(),
        )
        self._needs_vision: bool = False  # Set True when screenshots are in buffer
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

    def set_session_constraints(self, rendered: str | None) -> None:
        """Set the pre-rendered session-constraint block for the next step.

        See weebot.domain.models.session_constraint.SessionConstraintRegistry.render()
        and tasks/specs/side_constraint_integrity_plan.md Phase 4. Delivered
        as messages[-1] — the last message before the model's turn — never
        into _conversation_buffer, which is evictable (deque(maxlen=...))
        and rewritten wholesale on compaction.
        """
        self._session_constraints_block = rendered or None

    def _maybe_truncate_ponytail(self, text: str) -> str:
        """Truncate trailing prose after code fences when Ponytail is active.

        Returns *text* unchanged when the Ponytail skill is not present or
        when no code fence is found.
        """
        if not self._skill_prompt or "[Ponytail mode:" not in self._skill_prompt:
            return text
        return PonytailPostProcessor().truncate(text)

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
    def facts(self) -> dict[str, Any]:
        return dict(self._facts)

    def clear_facts(self) -> None:
        self._facts.clear()

    def _resolve_model_for_step(self, description: str) -> str | list[str]:
        """Return the best model for *description*, preferring vision when needed.

        Uses the task-model router for normal steps.  When ``_needs_vision`` is
        set (a screenshot was injected into the conversation buffer), returns a
        vision-capable VLM instead so the model can actually see the image.

        When ``WEEBOT_ENABLE_ACR`` is active, the ACR router's ordered
        candidate list is returned; ``CascadeExecutor`` handles list output.
        """
        if self._needs_vision:
            self._needs_vision = False  # Consume the flag for this call
            from weebot.config.model_refs import MODEL_VISION_PRIMARY
            return [MODEL_VISION_PRIMARY]
        return self._model_for_step(description)

    @staticmethod
    def _model_for_step(description: str) -> str | list[str]:
        """Return the best model(s) for *description*.

        When ``WEEBOT_ENABLE_ACR`` is True, returns an ordered candidate list
        from the AdaptiveCapabilityRouter.  Otherwise returns the static
        ``model_for_step(description)`` as a single-element list for
        backward compatibility with the cascade executor.

        Falls back to ``MODEL_CASCADE_TIER1`` if routing fails.
        """
        try:
            from weebot.config.feature_flags import WEEBOT_ENABLE_ACR
            if WEEBOT_ENABLE_ACR:
                from weebot.application.services.routing.adaptive_capability_router import (
                    AdaptiveCapabilityRouter,
                )
                router = AdaptiveCapabilityRouter()
                return router.route(description)
            from weebot.application.services.task_model_router import model_for_step
            return [model_for_step(description)]
        except Exception:
            return [MODEL_CASCADE_TIER1]


    @property
    def _last_expected_outcome(self) -> str | None:
        return self._context_compressor._last_expected_outcome

    @_last_expected_outcome.setter
    def _last_expected_outcome(self, value: str | None) -> None:
        self._context_compressor._last_expected_outcome = value

    @property
    def token_usage(self) -> dict[str, int]:
        """Cumulative real token usage for this executor instance."""
        prompt = self._context_compressor.total_prompt_tokens
        completion = self._context_compressor.total_completion_tokens
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }

    def __getattr__(self, name: str):
        """Delegate vision reflection helpers to the context compressor."""
        _ctx_map = {
            '_reflect_on_screenshot': 'reflect_on_screenshot',
            '_track_usage_and_maybe_compress': 'track_usage_and_maybe_compress',
        }
        if name in _ctx_map and '_context_compressor' in self.__dict__:
            return getattr(self._context_compressor, _ctx_map[name])
        raise AttributeError(f"'{type(self).__name__}' has no attribute {name!r}")

    def _vision_enabled(self) -> bool:
        """True when vision-in-the-loop feature flag is on.

        Does NOT check the current model — model switching to a VLM
        is handled by _resolve_model_for_step when screenshots are present.
        """
        return self._context_compressor.vision_enabled

    async def _inject_screenshot(self, tool_name: str, image_b64: str) -> None:
        """Forward to context compressor (kept for test compatibility)."""
        await self._context_compressor.inject_screenshot(tool_name, image_b64)

    def _inject_reflection(self, reflection: VisionReflection) -> None:
        """Forward to context compressor (inject_reflection stores expected_outcome)."""
        self._context_compressor.inject_reflection(reflection)

    def _reflection_enabled(self) -> bool:
        """True when BOTH vision-in-loop AND reflection flags are on.

        Does NOT check the current model — model switching to a VLM is handled
        separately via _needs_vision + _resolve_model_for_step.
        """
        from weebot.config.feature_flags import VISION_IN_LOOP_ENABLED, VISION_REFLECTION_ENABLED
        return VISION_IN_LOOP_ENABLED and VISION_REFLECTION_ENABLED

    async def execute_step(
        self, plan: Plan, step: Step, user_input: str | None = None,
        session_id: str = "",
    ) -> AsyncGenerator[AgentEvent, None]:
        self._facts.clear()
        self._should_terminate = False
        self._conversation_buffer.clear()

        # ── OTEL tracing: executor_step span ─────────────────────────
        # ARCH-AUDIT-V2 B2 — span for a single step within PlanActFlow.
        # Uses start_span (not start_as_current_span) for the same reason
        # as plan_act_iteration — the generator body makes context-manager
        # teardown unreliable.  Ended explicitly at the method's exit.
        # Gated on WEEBOT_OTEL_TRACING=true (default OFF).
        _step_span = None
        if self._tracing_port is not None:
            from weebot.config.feature_flags import is_enabled
            if is_enabled("OTEL_TRACING_ENABLED"):
                _step_span = self._tracing_port.start_span("executor_step")
                _step_span.set_attribute("step.id", step.id)
                _step_span.set_attribute("step.description", step.description[:200])
        self._current_step_id = step.id
        self._current_session_id = session_id or getattr(self, '_current_session_id', 'unknown')
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

        # ═══ Policy-error-loop tracking (Fix 5) ═══
        consecutive_error_class_counts: dict[str, int] = {}
        last_error_class: str | None = None

        base_prompt = self._load_prompt()

        # ── User profile from dialectic consolidation (lazy-init) ──
        if not hasattr(self, '_user_profile_cache'):
            try:
                import hashlib
                repo = self._state_repo
                if repo is not None:
                    key = hashlib.sha256(b"user_model_profile").hexdigest()[:16]
                    row = await repo.get_memory_entry(key)
                    txt = row.get("entry_text", "") if row else ""
                    self._user_profile_cache = txt[:500] if txt and txt != "No user data collected yet." else ""
                else:
                    self._user_profile_cache = ""
            except Exception:
                self._user_profile_cache = ""

        # ── Build system prompt via extracted builder ─────────────
        _step_scope = getattr(step, "context_scope", None)
        _scope_value = _step_scope.value if _step_scope is not None else "full"
        system_prompt = await build_executor_prompt(
            step_description=step.description,
            base_prompt=base_prompt,
            context_scope=_scope_value,
            harness_block=self._harness_instruction_block,
            skill_prompt=self._skill_prompt,
            skill_retriever=self._skill_retriever,
            behavioral_learner=self._behavioral_learner,
            state_repo=self._state_repo,
            personality=self._personality,
            profile_name=self._profile_name,
        )

        # ── Append extra components not handled by builder ────────
        # Gated by scope: minimal/skill steps don't need the cached user
        # profile blob (ICM per-step context scoping — see _prompt_builder).
        if _scope_value in ("full", "creative") and getattr(self, '_user_profile_cache', ''):
            system_prompt += f"\n\n## User Profile\n{self._user_profile_cache}"

        self._system_prompt = system_prompt
        # Inject OUTPUT_ROOT so tools resolve paths consistently
        from weebot.core.output_path import output_path as _op
        self._system_prompt = self._system_prompt + (
            f"\n\nOUTPUT_ROOT = {_op('Output')}"
            "\nALL file writes MUST use this absolute path prefix. "
            'Example: Set-Content -Path "{OUTPUT_ROOT}/refactor/file.md" -Value ...'
        )
        # Inject persistent memory snapshot
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
                "",
                f"Current step to execute: {step.description}",
                "",
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

        guard = IterationGuard(
            step_id=step.id,
            max_tool_calls_per_step=12,
            max_repeated_assistant_turns=2,
            repeated_tool_signature_limit=4,
        )
        step_result = ""
        loop_error: str | None = None
        abort_step = False
        thought_iteration: int = 0
        tool_calls_attempted: int = 0
        tool_calls_succeeded: int = 0
        semantic_loop_recoveries: int = 0
        _MAX_SEMANTIC_LOOP_RECOVERIES = 2

        # ── Tier 1.3: TrajectoryMonitor — reset per-step windows, preserve cross-step ──
        if self._trajectory_monitor is not None:
            self._trajectory_monitor.reset_step()
            self._trajectory_monitor.set_step_context(step.description or "")

        self._step_budget.reset()
        while self._step_budget.consume():
            guard.record_iteration()
            if guard.is_tool_call_budget_exhausted():
                logger.warning(
                    "Step %s: tool-call budget exhausted (%d calls). "
                    "Completing step with current findings.",
                    step.id, guard._max_tool_calls,
                )
                self._conversation_buffer.append({
                    "role": "user",
                    "content": (
                        "You have reached the maximum number of tool calls for this step. "
                        "Summarize what you found and complete the step. Do NOT call "
                        "any more tools."
                    ),
                })
                messages = sanitize_tool_call_pairing([
                    {"role": "system", "content": self._system_prompt}
                ] + list(self._conversation_buffer))
                try:
                    response = await self._cascade.call_with_cascade(
                        messages=messages,
                        description=step.description,
                    )
                    step_result = response.content or "Step completed (budget cap)."
                except Exception as exc:
                    logger.warning(
                        "Budget-cap summary call failed: %s — using fallback", exc
                    )
                    step_result = "Step completed (budget cap)."
                yield MessageEvent(role="assistant", message=step_result)
                abort_step = True
                break
            # ── Pre-call compaction: ensure the LLM sees compacted context ──
            await self._context_compressor._maybe_compress()

            messages = sanitize_tool_call_pairing([
                {"role": "system", "content": self._system_prompt}
            ] + list(self._conversation_buffer))

            # ── Lost-in-Compaction: session constraints as messages[-1] ──────
            # Paper's K_ub position (>98% compliance) — appended to the local
            # list, never the buffer, so it can't be evicted or compacted away.
            if self._session_constraints_block:
                messages.append({"role": "user", "content": self._session_constraints_block})

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
                response = await self._cascade.call_with_cascade(
                    messages, description=step.description
                )
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
                guard.record_assistant_turn(normalize_text(assistant_content))

                step_result = assistant_content or "No result"
                if follow_up_like(step_result):
                    step_result = "Step completed. Continuing to the next plan step."

                if guard.is_assistant_turn_loop():
                    loop_error = guard.build_stuck_error(
                        reason="repeated assistant-only responses with no tool progress",
                        step_description=step.description,
                    )
                    yield ErrorEvent(error=loop_error)
                    break

                step_result = self._maybe_truncate_ponytail(step_result)
                yield MessageEvent(role="assistant", message=step_result)
                break

            abort_step = False
            # ── Phase 2: Pre-flight checks (sequential) ─────────
            _batch_tool_calls: list[dict] = []
            for tc in response.tool_calls:
                tool_name = tc["function"]["name"]
                raw_arguments = tc["function"].get("arguments", "{}")
                signature = tool_signature(tool_name, raw_arguments)
                guard.record_tool_call(signature)

                if guard.is_tool_signature_loop():
                    loop_error = guard.build_stuck_error(
                        reason=f"repeated identical tool call '{tool_name}'",
                        step_description=step.description,
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
            for tc, result in zip(_batch_tool_calls, results, strict=False):
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
                                "SEMANTIC_LOOP for step %s — injecting recovery hint "
                                "(attempt %d/%d)",
                                step.id,
                                semantic_loop_recoveries,
                                _MAX_SEMANTIC_LOOP_RECOVERIES,
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
                        if last_error_class in (
                            "security_blocked",
                            "policy_denied",
                            "confirmation_required",
                        ):
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
                    if is_expected_failure(step.description or ""):
                        # TDD RED phase — non-zero exit is expected.
                        # Don't classify as an error for loop detection.
                        err_class = None
                    else:
                        err_class = classify_tool_error(result.error or result.output or "")
                    if err_class:
                        if err_class == last_error_class:
                            consecutive_error_class_counts[err_class] = \
                                consecutive_error_class_counts.get(err_class, 0) + 1
                        else:
                            consecutive_error_class_counts = {err_class: 1}
                            last_error_class = err_class

                        if (
                            consecutive_error_class_counts.get(err_class, 0)
                            >= _MAX_SAME_ERROR_CLASS
                        ):
                            loop_error = (
                                f"Step '{step.id}' is stuck: the same error class '{err_class}' "
                                f"has triggered {consecutive_error_class_counts[err_class]} "
                                "consecutive times. "
                                f"Last error: {(result.error or result.output)[:300]}. "
                                "Requesting user input to unblock."
                            )
                            yield ErrorEvent(error=loop_error)
                            yield WaitForUserEvent(
                                question=(
                                    f"The agent is blocked by a '{err_class}' policy and cannot "
                                    f"proceed with step: {step.description!r}.\n"
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
                    step_result = self._maybe_truncate_ponytail(
                        result.output or "Task completed"
                    )
                    yield MessageEvent(role="assistant", message=step_result)
                    self._step_budget.refund(self._step_budget.remaining)
                    abort_step = True
                    break

                _tool_content = str(result)
                if not result.is_error and is_untrusted_tool(tool_name):
                    _tool_content = wrap_untrusted(source=tool_name, content=_tool_content)
                self._conversation_buffer.append({
                    "role": "tool",
                    "content": _tool_content,
                    "tool_call_id": tc["id"],
                })

                # Vision-in-the-loop: let a vision-capable model SEE the screen
                # state a tool produced, instead of driving blind off DOM/OCR text.
                if getattr(result, "base64_image", None) and self._vision_enabled():
                    self._needs_vision = True  # Next LLM call must use a VLM
                    await self._context_compressor.inject_screenshot(tool_name, result.base64_image)
                    # Phase 2: structured observe→plan reflection (extra LLM call, opt-in).
                    # Grounded in the step description so the model can judge progress.
                    reflection = await self._context_compressor.reflect_on_screenshot(
                        tool_name, result.base64_image, task_context=step.description
                    )
                    if reflection is not None:
                        self._context_compressor.inject_reflection(reflection)

            if abort_step:
                break

        # Delegate to extracted step-completion handler
        async for event in self._handle_step_completion(
            abort_step=abort_step,
            loop_error=loop_error,
            step_result=step_result,
            recent_tool_signatures=list(guard.state.recent_tool_signatures),
            tool_calls_attempted=tool_calls_attempted,
            tool_calls_succeeded=tool_calls_succeeded,
            step=step,
        ):
            yield event
            if isinstance(event, ErrorEvent):
                loop_error = event.error

        # End the executor_step span (ARCH-AUDIT-V2 B2)
        if _step_span is not None:
            _step_span.end()

    # ── Phase 2: Parallel tool execution ─────────────────────────
    # Per-tool semaphore gating is handled by ToolCollection.execute().
    # The executor simply fires all tool calls concurrently via gather.

    async def _handle_step_completion(
        self,
        abort_step: bool,
        loop_error: str | None,
        step_result: str,
        recent_tool_signatures: list,
        tool_calls_attempted: int,
        tool_calls_succeeded: int,
        step: Step,
    ):
        """Handle post-execution step completion: success, failure, stuck, or hollow."""
        if (
            not abort_step
            and loop_error is None
            and self._step_budget.exhausted
            and not step_result
        ):
            loop_error = build_stuck_error(
                step=step,
                reason="max step budget reached",
                recent_signatures=recent_tool_signatures,
                max_steps=self._max_steps,
            )
            yield ErrorEvent(error=loop_error)

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
            yield StepEvent(
                step_id=step.id,
                description=step.description,
                status=StepStatus.FAILED,
            )
            return

        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.COMPLETED)

# ── Phase 2 helpers ────────────────────────────────────────────────────────────


def _maybe_record_skill_gap(
    executor: ExecutorAgent,
    step_description: str,
    best_score: float,
) -> None:
    """Record a skill-gap signal when retrieval misses the creation threshold.

    Two output paths:
    1. Append to ``executor._skill_gaps`` for downstream ``IdeaContract``
       creation (existing, processed in ``CompletedState``).
    2. Emit a ``SkillGapDetected`` domain event (new) for lightweight
       subscribers (misalignment journal, diagnostic logger).

    Never raises — both paths are purely additive.
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

    # Enhancement 5: emit SkillGapDetected domain event for lightweight subscribers
    try:
        from weebot.domain.models.event import SkillGapDetected

        event = SkillGapDetected(
            session_id=getattr(executor, "_current_session_id", "unknown"),
            step_description=step_description[:200],
            best_score=best_score,
        )
        if executor._event_bus is not None:
            import asyncio

            asyncio.ensure_future(
                executor._event_bus.publish_domain_event(event)
            )
    except Exception:
        logger.debug("SkillGapDetected event emission failed (non-blocking)")
        pass  # event emission must never block the execution loop
