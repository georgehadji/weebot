"""One guard chain for every tool that runs code (ICM fix plan W3.1, W3.2).

Before this, each shell tool hard-coded its own gate order: ``bash`` ran the
command analyzer, BashGuard and ExecApprovalPolicy; ``powershell`` ran only the
policy (F01); and the MCP server called the tools directly, outside the egress
check in ``ToolExecutor`` (F09). Here every guard is a small ``ToolGuard``
(Strategy) behind an Adapter over the existing core class, ``GuardChain``
(Chain of Responsibility) folds their verdicts with "most restrictive wins",
and ``GuardedTool`` (Decorator) runs the chain before the wrapped tool.

Modes (``WeebotSettings.shell_guard_mode``, env ``WEEBOT_SHELL_GUARD_MODE``):

* ``observe`` -- record the chain's verdict, then run the tool
  unchanged. The tool's own gates still apply. This is the dark launch: the
  log shows what enforcement would refuse before anything is refused.
* ``enforce`` (default) -- refuse DENY; hand ASK to the approval channel of ADR-013
  (``application/services/tool_approval.py``): Deny by default, a console
  prompt in the CLI, a flow pause in the web UI and gateways.

The core guards are unchanged; adapters only translate their results.
Lives in application/services (not tools/) so the MCP server can import it
without a new import-linter exemption.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Protocol

from pydantic import PrivateAttr

from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)

# Tools whose `command` argument is a shell command line.
SHELL_TOOLS: frozenset[str] = frozenset({"bash", "powershell"})
# Tools the composition roots wrap in GuardedTool.
GUARDED_TOOLS: frozenset[str] = frozenset({"bash", "powershell", "python_execute"})


class GuardAction(IntEnum):
    """Ordered so that ``max`` is the most restrictive."""

    ALLOW = 0
    ASK = 1
    DENY = 2


@dataclass(frozen=True)
class GuardVerdict:
    action: GuardAction
    guard: str
    reason: str = ""
    # An egress host the approver may allowlist for good (ADR-013 section 3).
    allow_always: str | None = None
    # Resolve this ASK through the approval channel even in observe mode: the
    # call cannot be undone (outbound_policy).
    enforce_always: bool = False


@dataclass(frozen=True)
class ChainResult:
    verdict: GuardVerdict  # the most restrictive one
    verdicts: tuple[GuardVerdict, ...]  # every guard that had something to say


class ToolGuard(Protocol):
    name: str

    def check(self, tool_name: str, args: Mapping[str, Any]) -> GuardVerdict | None:
        """Return a verdict, or None when this guard does not apply to the call."""


def _shell_command(tool_name: str, args: Mapping[str, Any]) -> str | None:
    if tool_name not in SHELL_TOOLS:
        return None
    command = args.get("command")
    return str(command) if command else None


# ── Adapters over the existing core guards ──────────────────────────────────


class BashGuardAdapter:
    """BLOCKED -> DENY, DANGEROUS -> ASK, SUSPICIOUS -> ALLOW with a note."""

    name = "bash_guard"

    def __init__(self, guard: Any | None = None) -> None:
        if guard is None:
            from weebot.core.bash_guard import BashGuard

            guard = BashGuard()
        self._guard = guard

    def check(self, tool_name: str, args: Mapping[str, Any]) -> GuardVerdict | None:
        command = _shell_command(tool_name, args)
        if command is None:
            return None
        from weebot.core.bash_guard import RiskLevel

        risk, checks = self._guard.evaluate(command)
        reason = "; ".join(c.description for c in checks if getattr(c, "description", ""))
        action = {
            RiskLevel.BLOCKED: GuardAction.DENY,
            RiskLevel.DANGEROUS: GuardAction.ASK,
        }.get(risk, GuardAction.ALLOW)
        if action is GuardAction.ALLOW and risk is not RiskLevel.SUSPICIOUS:
            return None
        return GuardVerdict(action, self.name, f"{risk.value}: {reason}".rstrip(": "))


class AnalyzerAdapter:
    """CommandSecurityAnalyzer: DANGEROUS -> DENY, SUSPICIOUS -> ALLOW with a note."""

    name = "command_analyzer"

    def __init__(self, analyzer: Any | None = None) -> None:
        if analyzer is None:
            from weebot.tools.bash_security import get_security_analyzer

            analyzer = get_security_analyzer()
        self._analyzer = analyzer

    def check(self, tool_name: str, args: Mapping[str, Any]) -> GuardVerdict | None:
        command = _shell_command(tool_name, args)
        if command is None:
            return None
        from weebot.tools.bash_security import CommandRiskLevel

        assessment = self._analyzer.analyze(command)
        if assessment.risk_level is CommandRiskLevel.SAFE:
            return None
        action = (
            GuardAction.DENY
            if assessment.risk_level is CommandRiskLevel.DANGEROUS
            else GuardAction.ALLOW
        )
        return GuardVerdict(
            action,
            self.name,
            f"{assessment.risk_level.value} (layer {assessment.layer_triggered}): "
            f"{assessment.reason}",
        )


class ApprovalPolicyAdapter:
    """ExecApprovalPolicy: not approved -> DENY, needs confirmation -> ASK."""

    name = "exec_approval_policy"

    def __init__(self, policy: Any | None = None) -> None:
        if policy is None:
            from weebot.core.approval_policy import ExecApprovalPolicy

            policy = ExecApprovalPolicy()
        self._policy = policy

    def check(self, tool_name: str, args: Mapping[str, Any]) -> GuardVerdict | None:
        from weebot.core.shell_segments import SegmentSyntax

        command = _shell_command(tool_name, args)
        syntax = SegmentSyntax.SHELL
        if command is None and tool_name == "python_execute" and args.get("code"):
            command = str(args["code"])  # python_execute runs the same policy on its code
            syntax = SegmentSyntax.PYTHON  # its lines are code, not separate commands
        if command is None:
            return None
        cwd = str(args["working_dir"]) if args.get("working_dir") else None
        result = self._policy.evaluate(command, syntax=syntax, cwd=cwd)
        if not result.approved:
            return GuardVerdict(GuardAction.DENY, self.name, result.reason)
        if result.requires_confirmation:
            return GuardVerdict(
                GuardAction.ASK, self.name, result.reason or result.undo_hint or "confirm"
            )
        return self._default_ask(tool_name, command, cwd)

    def _default_ask(
        self, tool_name: str, command: str, cwd: str | None = None
    ) -> GuardVerdict | None:
        """A shell segment no rule covers and that is not a plain read (audit A20, D3a).

        WEEBOT_SHELL_DEFAULT_ASK: ``off``; ``observe`` (default) logs "would ask" and lets it
        run, to count the extra prompts before enforcing; ``enforce`` asks. Shell tools only:
        python_execute must keep running calls such as ``executor.shutdown()`` unasked.
        """
        if tool_name not in SHELL_TOOLS:
            return None
        from weebot.config.settings import get_settings

        mode = get_settings().shell_default_ask
        if mode == "off":
            return None
        unreviewed = self._policy.unreviewed_segments(command, cwd=cwd)
        if not unreviewed:
            return None
        reason = f"no approval rule covers: {unreviewed[0][:120]}"
        if mode == "enforce":
            return GuardVerdict(GuardAction.ASK, self.name, reason)
        logger.warning("shell_default_ask would ask (%s): %s", tool_name, reason)
        return None


class EgressAdapter:
    """EgressGuard: an outbound call that needs approval -> ASK."""

    name = "egress_guard"

    def __init__(self, guard: Any | None = None) -> None:
        if guard is None:
            from weebot.core.egress_guard import EgressGuard

            guard = EgressGuard()
        self._guard = guard

    def check(self, tool_name: str, args: Mapping[str, Any]) -> GuardVerdict | None:
        decision = self._guard.classify(tool_name, dict(args))
        if not decision.requires_approval:
            return None
        from weebot.core.egress_guard import EgressReason

        # "Always allow this host" only for a new host with nothing else wrong.
        # Never for an internal target (loopback, link-local, private): see EgressGuard.
        first_time_only = decision.reasons == [EgressReason.FIRST_TIME_RECIPIENT] and not (
            decision.recipient and self._guard._is_internal(decision.recipient)
        )
        return GuardVerdict(
            GuardAction.ASK,
            self.name,
            decision.summary,
            allow_always=decision.recipient if first_time_only else None,
        )


def is_financial_tool(tool_name: str) -> bool:
    """True for a tool named like a payment action (F06, decision 3).

    No built-in tool is financial; one arrives from an external MCP server, by
    name, through any of three adapters. Matching names at the one place every
    collection passes (``guard_tools``) covers all of them. A misfire costs one
    extra question, the safe direction.
    """
    from fnmatch import fnmatchcase

    from weebot.config.settings import get_settings

    settings = get_settings()
    if not settings.financial_tools_always_ask:
        return False
    name = tool_name.lower()
    patterns = (p.strip().lower() for p in settings.financial_tool_patterns.split(","))
    return any(fnmatchcase(name, p) for p in patterns if p)


class FinancialToolAdapter:
    """A financial/payment tool -> ASK (``TOOL_CATEGORIES`` finance/payment)."""

    name = "financial_policy"

    def check(self, tool_name: str, args: Mapping[str, Any]) -> GuardVerdict | None:
        if not is_financial_tool(tool_name):
            return None
        return GuardVerdict(
            GuardAction.ASK, self.name, f"financial tool '{tool_name}' always asks"
        )


def is_outbound_tool(tool_name: str) -> bool:
    """True for a tool named like a publish/send/spend action.

    Like F06, these arrive from external MCP servers (Postiz, agentic-inbox),
    namespaced ``mcp__<server>__<tool>``, so they are matched by name
    (``WEEBOT_OUTBOUND_TOOL_PATTERNS``). A misfire costs one extra question.
    """
    from fnmatch import fnmatchcase

    from weebot.config.settings import get_settings

    name = tool_name.lower()
    patterns = (p.strip().lower() for p in get_settings().outbound_tool_patterns.split(","))
    if any(fnmatchcase(name, p) for p in patterns if p):
        return True
    # MCP tools fail closed: one that does not read by its name asks (F38).
    return name.startswith("mcp__") and not _mcp_tool_reads(tool_name)


_READ_VERBS = frozenset(
    {"get", "list", "search", "fetch", "read", "download", "schema", "status", "find", "query"}
)
_WRITE_VERBS = frozenset(
    {
        "create", "update", "delete", "remove", "add", "assign", "move", "transition",
        "edit", "upload", "trigger", "call", "abort", "set", "post", "send", "publish",
        "schedule", "report", "upsert", "merge", "archive", "close", "submit", "run",
        "execute", "write", "import", "invite", "cancel", "approve", "reply",
    }
)
# Postiz names these like actions, but they only read provider data.
_MCP_READ_TOOLS = frozenset({"triggertool", "videofunctiontool"})


def _mcp_tool_reads(tool_name: str) -> bool:
    """True when ``mcp__<server>__<tool>`` reads by its name: it starts with a read
    verb (``jira_get_issue``), or ends with one and has no write verb (``groupList``)."""
    import re

    _, server, *rest = tool_name.split("__")
    tool = rest[-1] if rest else ""
    if tool.lower() in _MCP_READ_TOOLS:
        return True
    words = [
        w.lower()
        for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", tool)
        if w.lower() not in (server.lower(), "tool")
    ]
    if words[:1] == ["batch"]:
        words = words[1:]
    if not words:
        return False
    if words[0] in _READ_VERBS:
        return True
    return words[-1] in _READ_VERBS and not _WRITE_VERBS.intersection(words)


class OutboundToolAdapter:
    """A publishing/sending/spending tool -> ASK, honoured even in observe mode.

    Observe mode exists to collect guard data before enforcing; a public post
    or a sent mail cannot be taken back, so waiting for that data is not safe
    here. ``WEEBOT_OUTBOUND_ASK_IN_OBSERVE=false`` makes it log-only again.
    """

    name = "outbound_policy"

    def check(self, tool_name: str, args: Mapping[str, Any]) -> GuardVerdict | None:
        if not is_outbound_tool(tool_name):
            return None
        from weebot.config.settings import get_settings

        return GuardVerdict(
            GuardAction.ASK,
            self.name,
            f"outbound tool '{tool_name}' publishes, sends or spends; it always asks",
            enforce_always=get_settings().outbound_ask_in_observe,
        )


# ── Chain and decorator ─────────────────────────────────────────────────────


class GuardChain:
    """Ask every guard; the most restrictive verdict wins.

    A guard that raises yields DENY: a security gate that cannot run does not
    report clean (the project's fail-closed rule).
    """

    def __init__(self, guards: Iterable[ToolGuard]) -> None:
        self._guards = tuple(guards)

    def evaluate(self, tool_name: str, args: Mapping[str, Any]) -> ChainResult:
        verdicts: list[GuardVerdict] = []
        for guard in self._guards:
            try:
                verdict = guard.check(tool_name, args)
            except Exception as exc:
                logger.exception("tool guard %s failed on %s", guard.name, tool_name)
                verdict = GuardVerdict(GuardAction.DENY, guard.name, f"guard failed: {exc}")
            if verdict is not None:
                verdicts.append(verdict)
        worst = max(
            verdicts,
            key=lambda v: v.action,
            default=GuardVerdict(GuardAction.ALLOW, "chain"),
        )
        return ChainResult(worst, tuple(verdicts))


def default_guard_chain(*, include_egress: bool = True) -> GuardChain:
    """The full chain. Flows pass ``include_egress=False``: ToolExecutor already
    gates egress (and routes its ASK to the same approval channel), so a second
    egress check here would ask twice for one call."""
    guards: list[ToolGuard] = [
        BashGuardAdapter(),
        AnalyzerAdapter(),
        ApprovalPolicyAdapter(),
        FinancialToolAdapter(),
        OutboundToolAdapter(),
    ]
    if include_egress:
        guards.append(EgressAdapter())
    return GuardChain(guards)


def shell_guard_mode() -> str:
    from weebot.config.settings import get_settings

    return get_settings().shell_guard_mode


class GuardedTool(BaseTool):
    """Runs a GuardChain before the wrapped tool; see the module docstring."""

    _inner: BaseTool = PrivateAttr()
    _chain: GuardChain = PrivateAttr()
    _mode: str = PrivateAttr(default="observe")
    _approval: Any = PrivateAttr(default=None)  # ApprovalPort; None -> current channel

    @classmethod
    def wrap(
        cls,
        inner: BaseTool,
        chain: GuardChain,
        mode: str = "observe",
        approval: Any | None = None,
    ) -> GuardedTool:
        tool = cls(
            name=inner.name,
            description=inner.description,
            parameters=inner.parameters,
            max_concurrent=inner.max_concurrent,
            default_timeout_seconds=inner.default_timeout_seconds,
            truncation_strategy=inner.truncation_strategy,
        )
        tool._inner = inner
        tool._chain = chain
        tool._mode = mode
        tool._approval = approval
        return tool

    @property
    def inner(self) -> BaseTool:
        return self._inner

    def resolved_output_trust(self):
        # A guard wrapper adds no trust of its own: what comes back is the wrapped
        # tool's output, so the wrapped tool's declaration decides (SEC-1).
        return self._inner.resolved_output_trust()

    async def execute(self, **kwargs: Any) -> ToolResult:
        result = self._chain.evaluate(self.name, kwargs)
        verdict = result.verdict
        if result.verdicts:
            level = logging.WARNING if verdict.action > GuardAction.ALLOW else logging.INFO
            logger.log(
                level,
                "tool guard [%s] %s: %s by %s (%s); all: %s",
                self._mode,
                self.name,
                verdict.action.name,
                verdict.guard,
                verdict.reason,
                ", ".join(f"{v.guard}={v.action.name}" for v in result.verdicts),
            )
        if self._mode == "enforce" and verdict.action is GuardAction.DENY:
            # DENY is never approvable (ADR-013 section 2).
            return ToolResult(
                output="", error=f"Tool call denied by {verdict.guard}: {verdict.reason}"
            )
        enforced_ask = any(
            v.enforce_always for v in result.verdicts if v.action is GuardAction.ASK
        )
        if verdict.action is GuardAction.ASK and (self._mode == "enforce" or enforced_ask):
            refused = await self._resolve_ask(kwargs, result)
            if refused is not None:
                return refused
            from weebot.core.approval import human_approved_call

            with human_approved_call(self._inner.name):
                return await self._inner.execute(**kwargs)
        return await self._inner.execute(**kwargs)

    async def _resolve_ask(self, kwargs: dict[str, Any], result: ChainResult) -> ToolResult | None:
        """Hand an ASK to the approval channel; None means "run the call"."""
        from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval
        from weebot.application.services import tool_approval
        from weebot.core.approval import call_fingerprint

        fingerprint = call_fingerprint(self.name, kwargs)
        if tool_approval.already_approved(fingerprint):
            return None  # a human approved this exact call at an earlier gate
        hosts = {v.allow_always for v in result.verdicts if v.action is GuardAction.ASK}
        request = ToolCallApproval(
            session_id=tool_approval.current_session_id(),
            tool_name=self.name,
            arguments=dict(kwargs),
            fingerprint=fingerprint,
            guard=result.verdict.guard,
            reason=result.verdict.reason,
            # Offer "always allow this host" only when every ASK is that one host.
            allow_always=next(iter(hosts)) if len(hosts) == 1 and None not in hosts else None,
        )
        approval = self._approval or tool_approval.current_approval()
        outcome = await approval.resolve(request)
        if outcome is ApprovalOutcome.APPROVED:
            return None
        if outcome is ApprovalOutcome.PENDING:
            return tool_approval.pending_result(request)
        return tool_approval.denied_result(request)

    async def health_check(self) -> bool:
        return await self._inner.health_check()

    async def close(self) -> None:
        await self._inner.close()


def guard_tools(
    tools: Iterable[BaseTool],
    *,
    chain: GuardChain | None = None,
    mode: str | None = None,
    include_egress: bool = True,
) -> list[BaseTool]:
    """Wrap the GUARDED_TOOLS, financial and outbound tools among *tools*."""
    tools = list(tools)
    needs = [
        not isinstance(t, GuardedTool)
        and (t.name in GUARDED_TOOLS or is_financial_tool(t.name) or is_outbound_tool(t.name))
        for t in tools
    ]
    if not any(needs):
        return tools
    chain = chain or default_guard_chain(include_egress=include_egress)
    mode = mode or shell_guard_mode()
    return [
        GuardedTool.wrap(t, chain, mode) if need else t
        for t, need in zip(tools, needs, strict=True)
    ]
