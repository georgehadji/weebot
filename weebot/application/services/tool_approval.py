"""Tool-call approval: the three ADR-013 strategies and the channel scope.

``GuardedTool`` (enforce mode) and the egress gate in ``ToolExecutor`` hand an
ASK verdict to ``current_approval()``:

* ``DenyApproval`` -- the process default: cron, webhooks, MCP, any run
  without a human. ASK is refused.
* ``ConsoleApproval`` -- CLI with a TTY: the call waits on a prompt.
* ``FlowPauseApproval`` -- web UI and chat gateways: the call is answered
  ``PENDING``; the executor emits ``ToolApprovalEvent``, the flow pauses with
  gate ``"tool_approval"``, and on "yes" ``FlowRouter`` records a grant through
  ``record_flow_reply`` and the step runs again.

Grants live in one process-wide ``ApprovalManager``: single use, bound to
``call_fingerprint(tool, args)``, 10-minute expiry, session-scoped. Entry
points pick the channel with ``set_process_approval``; a headless run inside
an interactive process narrows it with ``approval_scope(approval=DenyApproval())``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from weebot.application.ports.approval_port import (
    ApprovalOutcome,
    ApprovalPort,
    ToolCallApproval,
)
from weebot.application.ports.guardian_port import GuardianPort, GuardianVerdict
from weebot.core.approval import ApprovalManager
from weebot.core.approval_scopes import ScopedGrants
from weebot.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)

APPROVAL_DATA_KEY = "approval_required"
DENIAL_DATA_KEY = "approval_denied"  # on a result a person, a rule or a guard refused (H18d)
ALWAYS_TOKENS = frozenset({"always", "always allow", "allow always", "always allow host"})
SESSION_TOKENS = frozenset({"session", "yes for this session", "allow for this session"})

# ── Journal (ADR-013: outcomes, not only requests, reach the event store) ──

_journal_store: Any = None  # EventStorePort, set by the entry point
_journal_writes: set[asyncio.Task] = set()  # strong refs until each write lands


def set_approval_journal(store: Any | None) -> None:
    """Journal approval outcomes to *store* (an ``EventStorePort``); None stops it."""
    global _journal_store
    _journal_store = store


def _journal(event_type: str, session_id: str, data: dict[str, Any]) -> None:
    """Best effort, like DurableEventBus: a failed write is logged, never raised."""
    store = _journal_store
    if store is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("approval journal skipped, no event loop: %s", event_type)
        return
    task = loop.create_task(store.log_event(session_id, event_type, data))
    _journal_writes.add(task)
    task.add_done_callback(_journal_done)


def _journal_done(task: asyncio.Task) -> None:
    _journal_writes.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("approval journal write failed: %r", task.exception())


def _journal_outcome(event_type: str, request: ToolCallApproval, channel: str) -> None:
    # No arguments: they may hold secrets; the fingerprint identifies the call.
    _journal(
        event_type,
        request.session_id,
        {
            "tool_name": request.tool_name,
            "guard": request.guard,
            "fingerprint": request.fingerprint,
            "channel": channel,
        },
    )


def _journal_expired(session_id: str, fingerprint: str) -> None:
    _journal("approval_expired", session_id, {"fingerprint": fingerprint})


_GRANTS = ApprovalManager(on_expired=_journal_expired)


def grant_store() -> ApprovalManager:
    return _GRANTS


_SCOPES = ScopedGrants()
_guardian: GuardianPort | None = None  # set by the entry point when WEEBOT_APPROVAL_GUARDIAN is on


def set_guardian(guardian: GuardianPort | None) -> None:
    """Let *guardian* review the commands no rule covers before a person is asked (H18c)."""
    global _guardian
    _guardian = guardian


async def guardian_outcome(request: ToolCallApproval) -> ApprovalOutcome | None:
    """APPROVED or DENIED by the guardian, or None: ask the approval channel as usual.

    Only a call that can carry a scope pattern goes to it (no rule covers the command; not
    dangerous, not a floor, not egress, not the untrusted-content gate), only in a session the
    executor said is untainted, and never when a scope already covers the call.
    """
    command = request.arguments.get("command")
    if (
        _guardian is None
        or not request.pattern
        or not isinstance(command, str)
        or _scope_tainted.get() is not False
        or _SCOPES.allows(request.session_id, request.pattern)
    ):
        return None
    verdict = await _guardian.review(command, _scope_step.get())
    if verdict is GuardianVerdict.APPROVE:
        _journal_outcome("approval_granted", request, "guardian")
        return ApprovalOutcome.APPROVED
    if verdict is GuardianVerdict.DENY:
        _journal_outcome("approval_denied", request, "guardian")
        return ApprovalOutcome.DENIED
    return None


def scope_store() -> ScopedGrants:
    return _SCOPES


def _scope_covers(request: ToolCallApproval) -> bool:
    """True when a session or always scope a human gave already covers this call (H18b)."""
    scope = _SCOPES.allows(request.session_id, request.pattern)
    if scope is None:
        return False
    logger.info("approval scope used (%s): %s", scope, request.pattern)
    _journal_outcome("approval_granted", request, f"scope_{scope}")
    return True


class DenialBreaker:
    """Counts refused tool calls: too many in a step, or in a session, and a person decides (H18d).

    ``record`` returns ``"step"`` or ``"session"`` on the call that trips it, else None. A trip
    clears both counts: the person has been asked, and the next refusals start a new tally.
    """

    def __init__(self, per_step: int = 3, per_session: int = 6) -> None:
        self._per_step = per_step
        self._per_session = per_session
        self._steps: dict[tuple[str, str], int] = {}
        self._sessions: dict[str, int] = {}

    def record(self, session_id: str, step_id: str) -> str | None:
        key = (session_id, step_id)
        self._steps[key] = self._steps.get(key, 0) + 1
        self._sessions[session_id] = self._sessions.get(session_id, 0) + 1
        if self._sessions[session_id] >= self._per_session:
            tripped = "session"
        elif self._steps[key] >= self._per_step:
            tripped = "step"
        else:
            return None
        self._sessions.pop(session_id, None)
        for step_key in [k for k in self._steps if k[0] == session_id]:
            del self._steps[step_key]
        logger.warning(
            "denial breaker tripped (%s): session=%s step=%s", tripped, session_id, step_id
        )
        return tripped

    def forget_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        for step_key in [k for k in self._steps if k[0] == session_id]:
            del self._steps[step_key]


_BREAKER = DenialBreaker()


def denial_breaker() -> DenialBreaker:
    return _BREAKER


# ── Strategies ──────────────────────────────────────────────────────────────


class DenyApproval(ApprovalPort):
    """No human can answer: refuse (today's behaviour, and the safe default)."""

    async def resolve(self, request: ToolCallApproval) -> ApprovalOutcome:
        logger.info(
            "approval denied (no interactive channel): %s by %s", request.tool_name, request.guard
        )
        _journal_outcome("approval_denied", request, "deny")
        return ApprovalOutcome.DENIED


class AutoApproval(ApprovalPort):
    """AUTO execution mode: no human is asked, so every ASK is granted.

    Scoped to a single step through ``approval_scope`` by the executor; the
    journal still records each grant (``channel="auto"``), so the audit trail
    ADR-013 promises survives the mode that removes the prompt.
    """

    async def resolve(self, request: ToolCallApproval) -> ApprovalOutcome:
        if request.human_only:
            # An approval floor: a person answers even in AUTO, and their grant is spent here.
            return await FlowPauseApproval().resolve(request)
        logger.warning(
            "approval auto-granted (AUTO execution mode): %s by %s",
            request.tool_name,
            request.guard,
        )
        _journal_outcome("approval_granted", request, "auto")
        return ApprovalOutcome.APPROVED


class FlowPauseApproval(ApprovalPort):
    """Pause the flow and ask; run the call once a grant for it exists."""

    def __init__(self, grants: ApprovalManager | None = None) -> None:
        self._grants = grants or _GRANTS

    async def resolve(self, request: ToolCallApproval) -> ApprovalOutcome:
        if not request.session_id:
            # A flow pause needs a session to resume; without one nobody can answer.
            return ApprovalOutcome.DENIED
        if self._grants.consume(request.session_id, request.fingerprint):
            logger.info("approval grant used: %s %s", request.tool_name, request.fingerprint[:12])
            return ApprovalOutcome.APPROVED
        if _scope_covers(request):
            return ApprovalOutcome.APPROVED
        return ApprovalOutcome.PENDING


async def _input(prompt: str) -> str:
    # to_thread: a bare input() would stop every other task on the event loop.
    return await asyncio.to_thread(input, prompt)


class ConsoleApproval(ApprovalPort):
    """Ask on the terminal and wait. EOF or Ctrl-C denies."""

    def __init__(self, ask: Callable[[str], Awaitable[str]] = _input) -> None:
        self._ask = ask

    async def resolve(self, request: ToolCallApproval) -> ApprovalOutcome:
        if _scope_covers(request):
            return ApprovalOutcome.APPROVED
        options = (
            "[y] once  [a] always allow this host  [n] no" if request.allow_always else "[y/N]"
        )
        if request.pattern:
            options = f"[y] once  [s] this session  [a] always allow '{request.pattern}'  [n] no"
        question = f"\n{approval_prompt(request, short=True)}\nApprove? {options}: "
        try:
            answer = (await self._ask(question)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            logger.info("approval prompt closed, denying %s", request.tool_name)
            answer = ""
        if answer in ("y", "yes"):
            _journal_outcome("approval_granted", request, "console")
            return ApprovalOutcome.APPROVED
        if answer in ("a", "always") and request.allow_always:
            allow_host(request.allow_always)
            _journal_outcome("approval_granted", request, "console_always")
            return ApprovalOutcome.APPROVED
        if request.pattern and answer in ("s", "session", "a", "always"):
            scope = "session" if answer in ("s", "session") else "always"
            _SCOPES.grant(scope, request.session_id, request.pattern)
            _journal_outcome("approval_granted", request, f"console_{scope}")
            return ApprovalOutcome.APPROVED
        _journal_outcome("approval_denied", request, "console")
        return ApprovalOutcome.DENIED


def allow_host(host: str) -> None:
    """Persist an egress recipient (W3.5, F08: approve_recipient's first caller)."""
    from weebot.core.egress_guard import EgressGuard

    EgressGuard().approve_recipient(host)
    logger.info("egress host allowlisted by a human: %s", host)


# ── Channel scope ───────────────────────────────────────────────────────────

_process_approval: ApprovalPort = DenyApproval()
_scope_approval: ContextVar[ApprovalPort | None] = ContextVar("weebot_approval", default=None)
_scope_session: ContextVar[str] = ContextVar("weebot_approval_session", default="")
_approved_call: ContextVar[str] = ContextVar("weebot_approved_call", default="")
# What the guardian needs of the running step; None until the executor says (H18c).
_scope_tainted: ContextVar[bool | None] = ContextVar("weebot_approval_tainted", default=None)
_scope_step: ContextVar[str] = ContextVar("weebot_approval_step", default="")


def set_process_approval(port: ApprovalPort) -> None:
    """Choose the channel for this process (called once by an entry point)."""
    global _process_approval
    _process_approval = port


def current_approval() -> ApprovalPort:
    return _scope_approval.get() or _process_approval


def current_session_id() -> str:
    return _scope_session.get()


def already_approved(fingerprint: str) -> bool:
    """True inside a call a human already approved at an earlier gate."""
    return bool(fingerprint) and _approved_call.get() == fingerprint


@contextmanager
def approval_scope(
    *,
    approval: ApprovalPort | None = None,
    session_id: str | None = None,
    approved_call: str | None = None,
    tainted: bool | None = None,
    step_description: str | None = None,
) -> Iterator[None]:
    tokens = []
    if tainted is not None:
        tokens.append((_scope_tainted, _scope_tainted.set(tainted)))
    if step_description is not None:
        tokens.append((_scope_step, _scope_step.set(step_description)))
    if approval is not None:
        tokens.append((_scope_approval, _scope_approval.set(approval)))
    if session_id is not None:
        tokens.append((_scope_session, _scope_session.set(session_id)))
    if approved_call is not None:
        tokens.append((_approved_call, _approved_call.set(approved_call)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


# ── Flow pause plumbing ─────────────────────────────────────────────────────


def _redact(value: Any) -> Any:
    from weebot.core.credential_sanitizer import sanitize

    return sanitize(value) if isinstance(value, str) else value


# How much of a call the prompt shows (R15). The approval always covers the whole call, so
# what does not fit is cut from the middle, never the end, and the prompt says how much.
_PROMPT_CHARS = 4000
_SHORT_PROMPT_CHARS = 800  # chat gateways
_VALUE_CHARS = 1500


def _elide(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]} …[{len(text) - limit:,} characters hidden]… {text[-tail:]}"


def render_call(arguments: dict[str, Any], *, limit: int = _PROMPT_CHARS) -> str:
    """Every argument of a call, redacted, with both ends of anything too long (R15).

    The prompt used to show ``command[:500]`` and nothing for other tools: a harmless first
    500 characters hid a destructive tail, and paid tools were approved blind.
    """
    command = arguments.get("command") or arguments.get("code")
    parts = [str(_redact(str(command)))] if command else []
    for key, value in arguments.items():
        if command is not None and value is command:
            continue
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        parts.append(f"{key}={_elide(str(_redact(text)), _VALUE_CHARS)}")
    return _elide("\n".join(parts), limit)


def approval_prompt(request: ToolCallApproval, *, short: bool = False) -> str:
    call = render_call(
        request.arguments, limit=_SHORT_PROMPT_CHARS if short else _PROMPT_CHARS
    )
    lines = [
        f"Tool '{request.tool_name}' needs your approval ({request.guard}: {request.reason}).",
        f"Call: {call}" if call else "",
    ]
    if not short:
        lines.append(
            "Reply 'yes' to run this exact call once"
            + (
                f", 'always' to run it and allow '{request.allow_always}' from now on"
                if request.allow_always
                else ""
            )
            + (
                f", 'session' to allow '{request.pattern}' for this session"
                f", 'always' to allow it from now on"
                if request.pattern
                else ""
            )
            + ", or say what to do instead."
        )
    return "\n".join(line for line in lines if line)


def pending_result(request: ToolCallApproval) -> ToolResult:
    """The result a PENDING call returns; ExecutorAgent turns it into ToolApprovalEvent."""
    message = f"Approval required before '{request.tool_name}' runs: {request.reason}"
    return ToolResult(
        output="",
        error=message,
        data={
            APPROVAL_DATA_KEY: {
                "tool_name": request.tool_name,
                "arguments": {k: _redact(v) for k, v in request.arguments.items()},
                "fingerprint": request.fingerprint,
                "guard": request.guard,
                "reason": request.reason,
                "allow_always": request.allow_always,
                "pattern": request.pattern,
                "human_only": request.human_only,
                "prompt": approval_prompt(request),
            }
        },
    )


def denied_result(request: ToolCallApproval) -> ToolResult:
    error = (
        f"Tool call needs approval by {request.guard}: {request.reason}. No interactive "
        "approval channel is available here; run it from the CLI or the web UI to approve."
    )
    if "inline script" in request.reason.lower():
        # Without a route the agent tried shape after shape (one task: 145 s).
        error += (
            " To run Python, use the python_execute tool, or write the script to a file"
            " under Output/ and run that file; both run without approval."
        )
    return ToolResult(output="", error=error, data={DENIAL_DATA_KEY: True})


def mark_tool_approval_pending(session: Any, event: Any) -> Any:
    """Pause bookkeeping for a ToolApprovalEvent: gate + what a "yes" approves.

    Sets the same ``_user_gate_pending`` key as ``_mark_user_gate`` in
    flows/states/executing.py (FlowRouter routes the reply on it), plus
    ``_tool_approval_pending`` for ``record_flow_reply``.
    """
    logger.info(
        "Tool '%s' requires approval (%s): %s", event.tool_name, event.risk_level, event.reason
    )
    extra = {
        **session.context.extra,
        "_user_gate_pending": "tool_approval",
        "_tool_approval_pending": {
            "tool_name": event.tool_name,
            "fingerprint": event.fingerprint,
            "allow_always": event.allow_always,
            "pattern": event.pattern,
        },
    }
    return session.model_copy(
        update={"context": session.context.model_copy(update={"extra": extra})}
    )


def record_flow_reply(
    session_id: str, pending: dict[str, Any], reply: str, *, approve_tokens: frozenset[str]
) -> bool:
    """Apply a human's reply to a paused tool call. Returns True when approved.

    Approval issues a single-use grant for the pending fingerprint; "always"
    (only offered for a first-time egress host) also allowlists that host.
    *approve_tokens* comes from the caller (FlowRouter) so this service does
    not import flows.
    """
    response = reply.strip().lower()
    fingerprint = pending.get("fingerprint", "")
    always_host = pending.get("allow_always")
    pattern = pending.get("pattern")
    scope_tokens = (SESSION_TOKENS | ALWAYS_TOKENS) if pattern else frozenset()
    approved = (
        response in approve_tokens
        or (bool(always_host) and response in ALWAYS_TOKENS)
        or response in scope_tokens
    )
    data = {"tool_name": pending.get("tool_name"), "fingerprint": fingerprint, "channel": "flow"}
    if not approved or not fingerprint:
        logger.info("approval declined for %s", pending.get("tool_name"))
        _journal("approval_denied", session_id, data)
        return False
    if always_host and response in ALWAYS_TOKENS:
        allow_host(always_host)
    if pattern and response in scope_tokens:
        _SCOPES.grant("session" if response in SESSION_TOKENS else "always", session_id, pattern)
    _GRANTS.grant(session_id, fingerprint)
    _journal("approval_granted", session_id, data)
    return True
