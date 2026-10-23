"""ToolExecutor — isolated tool dispatch for ExecutorAgent.

Responsible for executing individual tool calls and batches, managing
pre/post hooks, timeouts, and end-of-step summarization.  Extracted
from the original ExecutorAgent god class.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any
from collections.abc import AsyncGenerator
from collections import deque

from weebot.application.models.tool_collection import ToolCollection
from weebot.application.services.tool_call_repair import repair_json_string
from weebot.config.constants import TEMPERATURE_BALANCED
from weebot.core.egress_guard import is_enforcing
from weebot.core.trust_boundary import taints_egress_context
from weebot.domain.models.event import AgentEvent, MessageEvent
from weebot.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)


def _egress_blocked_result(name: str, decision) -> ToolResult:
    """Build the ToolResult returned in place of a blocked outbound call."""
    reasons_txt = ", ".join(r.value for r in decision.reasons)
    recipient_txt = f" to '{decision.recipient}'" if decision.recipient else ""
    message = (
        f"Outbound action blocked — requires human approval. "
        f"Tool '{name}'{recipient_txt} was stopped because: {reasons_txt}. "
        f"Detected patterns: {decision.detected_patterns[:3] or 'none'}. "
        f"To proceed, a human must explicitly approve this send."
    )
    return ToolResult.error_result(error=message, output=message, tool_name=name)


async def _ask_about_egress(session_id: str, name: str, args: dict, decision) -> ToolResult | None:
    """Route an egress ASK to the approval channel (ADR-013, W3.5).

    None means "approved, run it". The default Deny channel returns the same
    blocked result as before; Flow pause returns a pending result that
    ExecutorAgent turns into a ToolApprovalEvent; Console asks on the terminal.
    A new host with nothing else wrong may be allowlisted for good ("always").
    """
    from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval
    from weebot.application.services import tool_approval
    from weebot.core.approval import call_fingerprint
    from weebot.core.egress_guard import EgressReason

    first_time_only = decision.reasons == [EgressReason.FIRST_TIME_RECIPIENT]
    request = ToolCallApproval(
        session_id=session_id,
        tool_name=name,
        arguments=dict(args),
        fingerprint=call_fingerprint(name, args),
        guard="egress_guard",
        reason=decision.summary,
        allow_always=decision.recipient if first_time_only else None,
    )
    outcome = await tool_approval.current_approval().resolve(request)
    if outcome is ApprovalOutcome.APPROVED:
        logger.info("egress_guard: approved by a human — %s", decision.summary)
        return None
    if outcome is ApprovalOutcome.PENDING:
        return tool_approval.pending_result(request)
    logger.warning("egress_guard: blocked outbound tool call — %s", decision.summary)
    return _egress_blocked_result(name, decision)


async def _clear_network_use(
    guard, session_id: str, name: str, args: dict
) -> tuple[ToolResult | None, bool]:
    """Network-off sandbox (W3.9, decision 7): may this download use the network?

    Returns ``(refusal_or_None, network_ok)``. Applies only while
    ``SANDBOX_ALLOW_NETWORK`` is false and the call reaches the network
    (``EgressGuard.network_use``). A known host is cleared; detect-only egress
    mode clears everything; otherwise the first host asks through the ADR-013
    channel, and "always" allowlists it.
    """
    from weebot.config.settings import get_settings

    if get_settings().sandbox_allow_network:
        return None, False  # the sandbox network is on for every call anyway
    uses_network, host = guard.network_use(name, args)
    if not uses_network:
        return None, False
    if guard.is_known_recipient(host) or not is_enforcing():
        return None, True

    from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval
    from weebot.application.services import tool_approval
    from weebot.core.approval import call_fingerprint

    request = ToolCallApproval(
        session_id=session_id,
        tool_name=name,
        arguments=dict(args),
        fingerprint=call_fingerprint(name, args),
        guard="sandbox_network",
        reason=f"network access to {host or 'an unknown host'} (the sandbox network is off)",
        allow_always=host,
    )
    outcome = await tool_approval.current_approval().resolve(request)
    if outcome is ApprovalOutcome.APPROVED:
        return None, True
    if outcome is ApprovalOutcome.PENDING:
        return tool_approval.pending_result(request), False
    message = (
        f"Network access to {host or 'an unknown host'} needs approval: the sandbox network "
        "is off (SANDBOX_ALLOW_NETWORK=false). Approve it from the CLI or web UI, or allowlist "
        "the host."
    )
    return ToolResult.error_result(error=message, output=message, tool_name=name), False


def _is_local_url(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.scheme == "file" or parsed.hostname in ("localhost", "127.0.0.1", "::1")


# Sessions whose context holds untrusted external content (see ToolExecutor).
# shortcut: in-process only, so a resume in a new process starts untainted;
# move it to a session fact if resumes cross processes in practice.
_TAINTED_SESSIONS: set[str] = set()
# Session id -> whether its browser tab was last navigated to a local page.
_LOCAL_TAB: dict[str, bool] = {}
# Session id -> paths file_editor wrote in it (viewing them adds no external content).
_WRITTEN_FILES: dict[str, set[str]] = {}

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
        egress_guard=None,  # EgressGuard | None — resolved from DI when omitted
    ) -> None:
        self._tools = tools
        self._hooks = hooks
        self._conversation_buffer = conversation_buffer or deque(maxlen=15)
        self._system_prompt = system_prompt
        self._llm = llm
        self._model = model
        self._current_step_id: str = ""
        self._current_session_id: str = ""
        self._egress_guard = egress_guard
        self._egress_guard_resolved: bool = egress_guard is not None
        # True once any untrusted-output tool has run in this session. Egress
        # after that point always needs approval — the injected content is the
        # payload (the "lethal trifecta" escalation in egress_guard.py).
        self._tainted_here: bool = False

    @property
    def _untrusted_context_active(self) -> bool:
        # Per session, not per executor: each step builds a fresh executor.
        return self._tainted_here or self._current_session_id in _TAINTED_SESSIONS

    @_untrusted_context_active.setter
    def _untrusted_context_active(self, value: bool) -> None:
        self._tainted_here = value
        if value and self._current_session_id:
            _TAINTED_SESSIONS.add(self._current_session_id)

    # ── Dynamic context ────────────────────────────────────────────

    def set_step_context(self, step_id: str, session_id: str) -> None:
        """Update the current step/session context (called at step start)."""
        self._current_step_id = step_id
        self._current_session_id = session_id

    def _get_step_id(self) -> str:
        return self._current_step_id or "unknown"

    # ── Egress guard ───────────────────────────────────────────────

    def _get_egress_guard(self):
        """Resolve the DI-managed EgressGuard singleton, lazily.

        Only a SUCCESSFUL resolution latches. The previous version set
        `_egress_guard_resolved = True` before the `try`, so if both the DI
        lookup and the direct construction failed, `_egress_guard` stayed None
        and the early return above handed None back for the rest of the
        session — with `if guard is not None:` at the call site skipping
        classification entirely. The log said so in plain words: "outbound tool
        calls will NOT be gated". One construction hiccup ungated every
        subsequent send.

        Retrying is cheap next to that, and a transient failure now self-heals.
        """
        if self._egress_guard_resolved:
            return self._egress_guard
        from weebot.core.egress_guard import EgressGuard

        # Constructed directly. This used to build and configure a whole
        # Container() first, but its EgressGuard factory is `EgressGuard()` and
        # a fresh container shares nothing, so the result was the same (W5.3).
        try:
            self._egress_guard = EgressGuard()
        except Exception:
            logger.error(
                "egress_guard: unavailable — outbound tool calls will be BLOCKED "
                "while enforcement is on",
                exc_info=True,
            )
            self._egress_guard = None
            return None
        self._egress_guard_resolved = True
        return self._egress_guard

    @staticmethod
    def _could_be_egress(tool_name: str) -> bool:
        """Conservative name check for when the guard itself is unavailable.

        A security gate that cannot run must not report clean. Without the
        guard there is no way to inspect a bash command or a browser action, so
        the whole family is treated as outbound. Deliberately broader than
        `EgressGuard._detect_egress`: this runs only when the real classifier
        could not be built, and being wrong in the permissive direction is the
        failure this replaces.
        """
        from weebot.core.egress_guard import (
            _BROWSER_EGRESS_TOOLS,
            _NOTIFICATION_TOOLS,
        )

        lowered = tool_name.lower()
        if lowered in _BROWSER_EGRESS_TOOLS or lowered in _NOTIFICATION_TOOLS:
            return True
        return lowered in {"atomic_mail", "bash", "bash_tool", "powershell", "shell"}

    # ── Batch execution ────────────────────────────────────────────

    async def execute_tool_batch(self, tool_calls: list[dict]) -> list[ToolResult]:
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
        self, name: str, arguments: str | dict[str, Any] | None = None
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
            with contextlib.suppress(ValueError, TypeError):
                timeout = min(float(args["timeout"]) + 5.0, 305.0)

        # Pre-tool hook
        if self._hooks is not None:
            await self._hooks.execute_hooks(
                "pre_tool_call",
                {
                    "session_id": self._current_session_id,
                    "step_id": self._get_step_id(),
                    "tool_name": name,
                    "tool_args": args,
                },
            )

        # Gate outbound sends before they execute: payloads carrying secrets,
        # first-time recipients, and any egress from a session that has already
        # ingested untrusted content.
        guard = self._get_egress_guard()
        if guard is None:
            # The gate could not be built. Under the fail-closed policy for
            # security gates, an outbound-capable tool is refused rather than
            # waved through; everything else proceeds, so an unrelated import
            # error does not brick the agent.
            if is_enforcing() and self._could_be_egress(name):
                logger.error(
                    "egress_guard: unavailable — refusing possibly-outbound tool %r", name
                )
                _msg = (
                    f"Egress guard unavailable — '{name}' refused. A security gate "
                    f"that cannot verify does not report clean."
                )
                return ToolResult.error_result(error=_msg, output=_msg, tool_name=name)
        approved_call = ""
        network_ok = False  # W3.9: does this call get sandbox network?
        if guard is not None:
            decision = guard.classify(
                name, args, untrusted_context_active=self._untrusted_context_active
            )
            if decision.requires_approval:
                if is_enforcing():
                    refused = await _ask_about_egress(
                        self._current_session_id, name, args, decision
                    )
                    if refused is not None:
                        return refused
                    from weebot.core.approval import call_fingerprint

                    approved_call = call_fingerprint(name, args)
                else:
                    logger.warning(
                        "egress_guard: detect-only mode, allowing — %s", decision.summary
                    )
            # Egress that passed (allowlisted, approved, or detect-only) may use
            # the network; other network use (downloads) is cleared below.
            network_ok = decision.is_egress
            if not network_ok:
                refused, network_ok = await _clear_network_use(
                    guard, self._current_session_id, name, args
                )
                if refused is not None:
                    return refused

        import time as _timer

        from weebot.application.ports.sandbox_port import network_cleared_for_call
        from weebot.application.services.tool_approval import approval_scope

        _t0 = _timer.monotonic()
        try:
            # The session and any approval just given travel with the call, so
            # GuardedTool resolves its own ASK against the same session and does
            # not ask again for a call a human approved here (ADR-013).
            with (
                approval_scope(session_id=self._current_session_id, approved_call=approved_call),
                network_cleared_for_call() if network_ok else contextlib.nullcontext(),
            ):
                result = await asyncio.wait_for(
                    self._tools.execute(_name=name, **args), timeout=timeout
                )
        except TimeoutError:
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
            await self._hooks.execute_hooks(
                "post_tool_call",
                {
                    "session_id": self._current_session_id,
                    "step_id": self._get_step_id(),
                    "tool_name": name,
                    "tool_args": args,
                    "result": result,
                    "elapsed_ms": _elapsed,
                    "success": not isinstance(result, Exception),
                },
            )

        # External content has now entered the session; taint it so later egress
        # needs approval even to an already-known recipient. Errors carry no
        # external content, so they do not taint.
        #
        # Narrower than the fence in _base.py by FENCE_ONLY_TOOLS: fencing is
        # free, this taint is sticky for the rest of the session.
        # A file:// or loopback tab holds no external content, so reading it
        # does not taint. shortcut: tracked per session from the last navigate,
        # not the shared browser's real tab; read the tab URL if that drifts.
        if name == "advanced_browser" and args.get("url"):
            _LOCAL_TAB[self._current_session_id] = _is_local_url(str(args["url"]))
        local_page = name == "advanced_browser" and _LOCAL_TAB.get(self._current_session_id, False)
        # Writing a file returns only a confirmation; `view` returns its content,
        # which is new only if this session did not write the file.
        own_file = False
        if name == "file_editor":
            path = str(args.get("path", ""))
            written = _WRITTEN_FILES.setdefault(self._current_session_id, set())
            own_file = args.get("command") != "view" or path in written
            if args.get("command") != "view" and not getattr(result, "is_error", False):
                written.add(path)
        if (
            taints_egress_context(name)
            and not getattr(result, "is_error", False)
            and not (local_page or own_file)
        ):
            self._untrusted_context_active = True
        return result

    async def _execute_single_tool_call(self, tc: dict[str, Any]) -> ToolResult:
        """Thin wrapper: parse tool call dict and delegate to execute_tool."""
        return await self.execute_tool(
            tc["function"]["name"], tc["function"].get("arguments", "{}")
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
        self._conversation_buffer.append({"role": "user", "content": summary_prompt})
        system_prompt = self._system_prompt or _load_executor_system_prompt()
        messages = [{"role": "system", "content": system_prompt}] + list(self._conversation_buffer)
        response = await self._llm.chat(
            messages=messages, model=self._model, temperature=TEMPERATURE_BALANCED
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
