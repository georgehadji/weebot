"""Execution agent — executes a single step using available tools."""

from __future__ import annotations

import contextlib
import logging
from collections import deque
from pathlib import Path
from typing import Any, TYPE_CHECKING
from collections.abc import AsyncGenerator, Awaitable, Callable

if TYPE_CHECKING:
    from weebot.application.middleware.chain import MiddlewareChain
    from weebot.application.ports.provider_account_port import ProviderAccountPort
    from weebot.application.strategies.llm_pool import LLMPool
    from weebot.models.structured_output import VisionReflection

from weebot.application.agents.executor._iteration_guard import (
    DEFAULT_MAX_CONTEXT_TURNS,
    IterationGuard,
)
from weebot.application.agents.executor._step_setup import build_step_prompts, prime_step
from weebot.application.agents.executor._tool_batch import ToolBatchRunner
from weebot.application.agents.executor._turn import next_turn

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.hook_registry_port import HookRegistryPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.ponytail_post_processor import PonytailPostProcessor
from weebot.application.services.step_budget import StepBudget
from weebot.config.constants import MAX_EXECUTOR_STEPS
from weebot.config.model_refs import MODEL_CASCADE_TIER1
from weebot.core.trust_boundary import escalate, must_fence, trust_of, wrap_untrusted
from weebot.application.agents.executor._error_handler import (
    build_stuck_error,
    follow_up_like,
    normalize_text,
)
from weebot.domain.models.event import (
    AgentEvent,
    ErrorEvent,
    MessageEvent,
    StepEvent,
    StepStatus,
    ThoughtEvent,
)
from weebot.domain.models.plan import Plan, Step
from weebot.application.models.tool_collection import ToolCollection

logger = logging.getLogger(__name__)


# `sanitize_tool_call_pairing` now lives in `_tool_pairing.py` and
# `_merge_middleware_result` in `_tool_batch.py`, with the code that calls them
# (WB-06, phase 4.2).


def _load_executor_system_prompt() -> str:
    """Load the executor system prompt from the package or filesystem.

    Priority: (1) importlib.resources (packaged), (2) filesystem path
    (source checkout), (3) inline fallback constant.
    """
    # 1. Try importlib.resources (works when weebot is installed as a package)
    with contextlib.suppress(Exception):
        from importlib.resources import files as _resource_files

        return (
            _resource_files("weebot.config.prompts")
            .joinpath("executor_system.txt")
            .read_text(encoding="utf-8")
        )

    # 2. Try filesystem path (works in development / source checkout)
    with contextlib.suppress(Exception):
        if _EXECUTOR_SYSTEM_PROMPT_PATH.exists():
            return _EXECUTOR_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    # 3. Inline fallback — kept in sync with executor_system.txt
    return _EXECUTOR_SYSTEM_PROMPT_FALLBACK


# EXECUTOR_SYSTEM_PROMPT is loaded from weebot/config/prompts/executor_system.txt.
# An inline fallback is kept for environments where the file is not available.
_EXECUTOR_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / "executor_system.txt"
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
        personality=None,  # PersonalityManager (Phase 1.1)
        behavioral_learner=None,  # BehavioralLearner (Capability 5)
        prompt_variant_id: str | None = None,  # PromptRegistry variant (HyperAgents Enhancement 5)
        profile_name: str | None = None,  # SOUL.md profile (e.g. "coder", "researcher")
        agent_role: str | None = None,  # Agent role for per-role model selection
        hooks: HookRegistryPort | None = None,  # HookRegistryPort for pre/post tool call events
        harness_instruction_block: str | None = None,  # Self-Harness behavioural instructions
        middleware_chain: MiddlewareChain | None = None,  # MiddlewareChain — interceptor pipeline
        state_repo: StateRepositoryPort | None = None,  # State repository for user profile etc.
        tracing_port: (
            Any | None
        ) = None,  # TracingPort — OTEL distributed tracing (ARCH-AUDIT-V2 B2)
        trajectory_config: (
            Any | None
        ) = None,  # TrajectoryConfig — Trajectory Regulation Layer (Tier 1.3)
        session_constraints: str | None = None,  # Pre-rendered SessionConstraintRegistry.render()
        llm_pool: LLMPool | None = None,  # Global LLM concurrency bound -- see llm_pool.py
        provider_account: ProviderAccountPort | None = None,  # Credit check + live rescue
        pinned_model: str | None = None,  # `flow run --model`: the cascade tries it first
        # Injection scan for fenced tool output (plan 1.1b): a signal that names the
        # pattern and escalates trust, never the control. None = not configured.
        injection_scan: Callable[[str], dict[str, Any] | None] | None = None,
        # Outbound actions already taken, so a retried flow does not repeat them (ORCH-2).
        effect_ledger: Any | None = None,
        cost_meter: Any | None = None,  # SessionCostMeter: soft limit skips PREMIUM models
        # Awaitable returning the persistent-memory snapshot for the system prompt; the
        # composition root supplies it, so the executor imports no tool (plan 3.4).
        memory_snapshot: Callable[[], Awaitable[str]] | None = None,
        # Shared AdaptiveCapabilityRouter: ranks models per step and learns from outcomes.
        acr_router: Any | None = None,
    ):
        self._acr_router = acr_router
        self._memory_snapshot = memory_snapshot
        self._injection_scan = injection_scan
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
        self._skills_used: list[str] = []  # candidate skills injected into this step
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
            # No role (no SOUL.md profile) is still a step executor.
            agent_role=agent_role or "executor",
            model_provider=self._resolve_model_for_step,
            # This argument was missing from the only production construction
            # of CascadeExecutor, so the pool's bounded branch never executed
            # while an audit document recorded the bound as wired. Callers that
            # pass nothing still get the old unbounded behaviour; the one that
            # matters -- the container's step executor -- passes the pool.
            llm_pool=llm_pool,
            provider_account=provider_account,
            pinned_model=pinned_model,
            cost_meter=cost_meter,
            on_success=self._context_compressor.track_usage_and_maybe_compress,
            tracker=ModelCascadeTracker(),
            on_call_completed=self._publish_llm_call,
            acr_router=acr_router,
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
            effect_ledger=effect_ledger,
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

    async def _present_tool_output(self, tool_name: str, result: Any) -> str:
        """The text of a tool result as the model sees it: fenced unless the tool is LOCAL.

        Errors are fenced too (HTTP error pages and MCP messages carry remote
        text); the taint still skips them, see ``must_taint``. The scan is a
        signal: a hit names its pattern in the fence header, escalates a
        fixed-schema source to tainting, and records ``InjectionSuspected``. The
        content inside the fence is never altered.
        """
        content = str(result)
        trust = trust_of(self._tools.get_tool(tool_name) if self._tools is not None else None)
        if not must_fence(trust):
            return content

        detection = self._scan_tool_output(content)
        suspected = None
        if detection:
            suspected = str(detection.get("pattern") or detection.get("type") or "suspected")
            if escalate(trust, detection) != trust:
                self._tool_executor.taint_session(tool_name, getattr(result, "is_error", False))
            await self._emit_injection_suspected(tool_name, detection)
        return wrap_untrusted(source=tool_name, content=content, suspected=suspected)

    def _scan_tool_output(self, content: str) -> dict[str, Any] | None:
        if self._injection_scan is None or not content:
            return None
        try:
            return self._injection_scan(content)
        except Exception:
            # Fail closed: a scan that cannot run is a detection, not a clean bill.
            logger.warning("injection scan raised; treating the output as suspect", exc_info=True)
            return {
                "type": "scanner_unavailable",
                "pattern": "the injection scanner could not run",
                "severity": "critical",
                "unavailable": True,
            }

    async def _emit_injection_suspected(self, tool_name: str, detection: dict[str, Any]) -> None:
        from weebot.domain.models.event import InjectionSuspected

        session_id = getattr(self, "_current_session_id", "") or ""
        logger.warning(
            "injection suspected in %s output (session %s): %s [%s]",
            tool_name,
            session_id,
            detection.get("pattern"),
            detection.get("severity"),
        )
        if self._event_bus is None:
            return
        await self._event_bus.publish_domain_event(
            InjectionSuspected(
                session_id=session_id,
                step_id=str(getattr(self._tool_executor, "_get_step_id", lambda: "")() or ""),
                tool_name=tool_name,
                pattern=str(detection.get("pattern", "")),
                severity=str(detection.get("severity", "")),
                scanner_unavailable=bool(detection.get("unavailable", False)),
            )
        )

    async def _publish_llm_call(self, event: Any) -> None:
        """Stamp the step's session on an LLMCallCompleted and publish it (W4.1)."""
        if self._event_bus is None:
            return
        event.session_id = getattr(self, "_current_session_id", "") or ""
        await self._event_bus.publish_domain_event(event)

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

    def _model_for_step(self, description: str) -> str | list[str]:
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
                router = getattr(self, "_acr_router", None)
                if router is None:
                    from weebot.application.services.routing.adaptive_capability_router import (
                        AdaptiveCapabilityRouter,
                    )

                    router = AdaptiveCapabilityRouter()
                # Its top two only: each extra candidate is another paid probe on failure.
                return router.route(description)[:2]
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
            "_reflect_on_screenshot": "reflect_on_screenshot",
            "_track_usage_and_maybe_compress": "track_usage_and_maybe_compress",
        }
        if name in _ctx_map and "_context_compressor" in self.__dict__:
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

    _tool_note: str = ""

    def _scope_tools_for(self, step: Step) -> str:
        """Send this step only the tool definitions it needs (ICM B1); return the
        line naming the rest, which stay callable. All ~171 used to go every call."""
        from weebot.config.feature_flags import TOOL_SCOPE_ENABLED

        if self._tools is None or not hasattr(self._tools, "set_visible"):
            return ""
        if not TOOL_SCOPE_ENABLED:
            self._tools.set_visible(None)
            return ""
        from weebot.application.services.tool_scope import select_tools

        self._tools.set_visible(select_tools(step.description, {t.name for t in self._tools}))
        hidden = self._tools.hidden_names()
        if not hidden:
            return ""
        return (
            "\n\nMore tools exist (definitions not shown); call one by its exact name if the "
            "step needs it: " + ", ".join(hidden)
        )

    async def execute_step(
        self, plan: Plan, step: Step, user_input: str | None = None, session_id: str = ""
    ) -> AsyncGenerator[AgentEvent, None]:
        """Run one plan step to completion, yielding every event as it happens.

        This method is the loop's *shape*: setup, then turns until something stops it, then
        completion. What each turn does lives in `_turn.py`, what a tool batch does in
        `_tool_batch.py`, and what the first 130 lines of setup did in `_step_setup.py`.
        It was 527 lines with all of that inline (WB-06 in
        tasks/specs/arch_audit_2026_10_wave2_remediation_plan.md).
        """
        self._facts.clear()
        self._should_terminate = False
        self._conversation_buffer.clear()

        primed = prime_step(self, step, session_id)
        self._tool_note = primed.tool_note
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

        await build_step_prompts(self, plan, step, user_input)

        guard = IterationGuard(
            step_id=step.id,
            max_tool_calls_per_step=12,
            max_repeated_assistant_turns=2,
            repeated_tool_signature_limit=4,
        )
        batch = ToolBatchRunner()
        step_result = ""
        loop_error: str | None = None
        abort_step = False
        thought_iteration = 0

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
                    step.id,
                    guard._max_tool_calls,
                )
                step_result = await self._summarize_on_budget_cap(step)
                yield MessageEvent(role="assistant", message=step_result)
                abort_step = True
                break

            # Pre-call compaction: ensure the LLM sees compacted context.
            await self._context_compressor._maybe_compress()

            turn = await next_turn(self, step)
            for event in turn.events:
                yield event
            if turn.stop:
                break

            if turn.thought:
                thought_iteration += 1
                yield ThoughtEvent(
                    step_id=step.id, thought=turn.thought, iteration=thought_iteration
                )

            if not turn.response.tool_calls:
                guard.record_assistant_turn(normalize_text(turn.assistant_content))
                step_result = turn.assistant_content or "No result"
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

            outcome = await batch.run(
                self,
                step,
                list(turn.response.tool_calls),
                guard,
                step_result=step_result,
            )
            for event in outcome.events:
                yield event
            step_result = outcome.step_result
            if outcome.loop_error:
                loop_error = outcome.loop_error
            abort_step = outcome.abort_step
            if abort_step:
                break

        # Delegate to extracted step-completion handler
        async for event in self._handle_step_completion(
            abort_step=abort_step,
            loop_error=loop_error,
            step_result=step_result,
            recent_tool_signatures=list(guard.state.recent_tool_signatures),
            tool_calls_attempted=batch.tool_calls_attempted,
            tool_calls_succeeded=batch.tool_calls_succeeded,
            step=step,
        ):
            yield event
            if isinstance(event, ErrorEvent):
                loop_error = event.error

        if primed.span is not None:
            primed.span.end()

    async def _summarize_on_budget_cap(self, step: Step) -> str:
        """One last call asking for what the agent found, with tools withheld."""
        from weebot.application.agents.executor._tool_pairing import sanitize_tool_call_pairing

        messages = sanitize_tool_call_pairing(
            [{"role": "system", "content": self._system_prompt + self._tool_note}]
            + list(self._conversation_buffer)
        )
        try:
            response = await self._cascade.call_with_cascade(
                messages=messages, description=step.description
            )
            return response.content or "Step completed (budget cap)."
        except Exception as exc:
            logger.warning("Budget-cap summary call failed: %s — using fallback", exc)
            return "Step completed (budget cap)."

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
            yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.FAILED)
            return

        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.COMPLETED)


# ── Phase 2 helpers ────────────────────────────────────────────────────────────


def _maybe_record_skill_gap(
    executor: ExecutorAgent, step_description: str, best_score: float
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

    executor._skill_gaps.append({"step": step_description[:200], "score": best_score})
    logger.debug(
        "Phase 2: skill gap recorded (score=%.3f < %.3f) for step: %s",
        best_score,
        TAU_CREATE,
        step_description[:80],
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
            from weebot.core.background_tasks import get_background_tasks

            get_background_tasks().spawn(
                executor._event_bus.publish_domain_event(event), name="skill-gap-detected"
            )
    except Exception:
        logger.debug("SkillGapDetected event emission failed (non-blocking)")
        pass  # event emission must never block the execution loop
