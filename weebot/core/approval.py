"""Approval primitives for risky tool calls.

``ApprovalManager`` is the session-scoped grant store of ADR-013
(docs/adr/013-tool-call-approval.md); ``console_approval_callback`` is the
interactive prompt the Console strategy reuses. The strategies themselves
live in ``weebot/application/services/tool_approval.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Callable, Coroutine, Mapping
from typing import Any

from weebot.core.bash_guard import RiskLevel, SafetyCheck

logger = logging.getLogger(__name__)


class ApprovalDecision(str, Enum):
    """Possible decisions for an approval request."""

    APPROVED = "approved"  # Command can proceed
    DENIED = "denied"  # Command must not execute
    DEFERRED = "deferred"  # Decision postponed, ask again later


@dataclass(frozen=True)
class ApprovalRequest:
    """Request for user approval of a command.

    Attributes:
        command: The command to be executed
        risk_level: The assessed risk level
        checks: List of safety checks that triggered
        session_id: Optional session identifier
        context: Additional context about the command
    """

    command: str
    risk_level: RiskLevel
    checks: list[SafetyCheck] = field(default_factory=list)
    session_id: str | None = None
    context: dict = field(default_factory=dict)

    def format_prompt(self) -> str:
        """Format the approval prompt for CLI display.

        Returns:
            Formatted prompt string with ANSI color codes
        """
        risk_color = {
            RiskLevel.SAFE: "green",
            RiskLevel.SUSPICIOUS: "yellow",
            RiskLevel.DANGEROUS: "red",
            RiskLevel.BLOCKED: "red",
        }.get(self.risk_level, "white")

        lines = [
            "",
            "╔" + "═" * 78 + "╗",
            "║" + " COMMAND REQUIRES APPROVAL ".center(78) + "║",
            "╠" + "═" * 78 + "╣",
            f"║ Command: {self.command[:67]:<67} ║",
            f"║ Risk:    [{risk_color}]{self.risk_level.value.upper():<20}[/{risk_color}] {'':<44} ║",
            "╠" + "═" * 78 + "╣",
            f"║ Safety Concerns:{'':<62} ║",
        ]

        for check in self.checks:
            lines.append(f"║   • {check.description[:72]:<72} ║")
            lines.append(f"║     Suggestion: {check.suggestion[:59]:<59} ║")

        lines.extend(
            [
                "╠" + "═" * 78 + "╣",
                f"║ Options: [Y] Approve  [N] Deny  [S] Show details  [?] Help{'':<26} ║",
                "╚" + "═" * 78 + "╝",
                "",
            ]
        )

        return "\n".join(lines)

    def format_simple(self) -> str:
        """Format a simple text prompt (no ANSI codes).

        Returns:
            Plain text prompt suitable for logs or file output
        """
        lines = [
            "",
            "=" * 60,
            "COMMAND REQUIRES APPROVAL",
            "=" * 60,
            f"Command: {self.command}",
            f"Risk Level: {self.risk_level.value.upper()}",
            "",
            "Safety Concerns:",
        ]

        for check in self.checks:
            lines.append(f"  • {check.description}")
            lines.append(f"    Suggestion: {check.suggestion}")

        lines.extend(["", "Options: Y = Approve, N = Deny", "=" * 60, ""])

        return "\n".join(lines)


# Type alias for approval callback
ApprovalCallback = Callable[[ApprovalRequest], Coroutine[None, None, ApprovalDecision]]

# ADR-013: a grant lasts 10 minutes and is used once.
GRANT_TTL_SECONDS = 600.0


def call_fingerprint(tool_name: str, arguments: Mapping[str, Any]) -> str:
    """SHA-256 over the tool name and its canonical JSON arguments (ADR-013).

    Any changed character, path or flag gives a new fingerprint, so a grant
    can only ever authorise the exact call a human saw.
    """
    canonical = json.dumps(dict(arguments), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(f"{tool_name}\0{canonical}".encode()).hexdigest()


class ApprovalManager:
    """Session-scoped store of single-use tool-call grants (ADR-013, decision 2).

    A human approval becomes a grant for one exact call (``call_fingerprint``)
    in one session. ``consume`` returns True at most once per grant, and never
    after ``ttl_seconds``. There is no "approve the whole session" switch and
    no route by which a DENY verdict reaches this store: only ASK verdicts are
    offered for approval (``application/services/tool_approval.py``).

    This replaces the earlier prompt-and-cache manager, which approved by raw
    command string, could approve a whole session, and with
    ``auto_deny_blocked=False`` could approve a BLOCKED command (F07).
    """

    def __init__(
        self,
        ttl_seconds: float = GRANT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_sessions: int = 50,
        on_expired: Callable[[str, str], None] | None = None,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._max_sessions = max_sessions
        # Called with (session_id, fingerprint); the application journals it.
        self._on_expired = on_expired
        self._grants: dict[str, dict[str, float]] = {}  # session -> fingerprint -> expiry

    def grant(self, session_id: str, fingerprint: str) -> None:
        """Record a human approval of one exact call in one session."""
        if session_id not in self._grants and len(self._grants) >= self._max_sessions:
            self._grants.pop(next(iter(self._grants)))  # evict the oldest session
        self._grants.setdefault(session_id, {})[fingerprint] = self._clock() + self._ttl
        logger.info("approval grant issued: session=%s call=%s", session_id, fingerprint[:12])

    def consume(self, session_id: str, fingerprint: str) -> bool:
        """True once if an unexpired grant exists for this call; the grant is removed."""
        expiry = self._grants.get(session_id, {}).pop(fingerprint, None)
        if expiry is None:
            return False
        if self._clock() > expiry:
            logger.info("approval grant expired: session=%s call=%s", session_id, fingerprint[:12])
            if self._on_expired is not None:
                self._on_expired(session_id, fingerprint)
            return False
        return True


async def console_approval_callback(request: ApprovalRequest) -> ApprovalDecision:
    """Default console-based approval callback.

    This callback prompts the user for approval via console input.
    It supports interactive commands:
    - Y/y: Approve
    - N/n: Deny
    - S/s: Show details
    - ?: Show help

    Args:
        request: The approval request

    Returns:
        ApprovalDecision based on user input
    """
    # Try to use Rich for formatted output, fall back to plain text
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()

        # Format command with truncation if too long
        cmd = request.command
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."

        # Build panel content
        risk_colors = {
            RiskLevel.SAFE: "green",
            RiskLevel.SUSPICIOUS: "yellow",
            RiskLevel.DANGEROUS: "red",
            RiskLevel.BLOCKED: "red",
        }
        risk_color = risk_colors.get(request.risk_level, "white")

        content = Text()
        content.append("Command: ", style="bold")
        content.append(f"{cmd}\n\n", style="cyan")

        content.append("Risk Level: ", style="bold")
        content.append(request.risk_level.value.upper(), style=f"bold {risk_color}")
        content.append("\n\n")

        content.append("Safety Checks:\n", style="bold")
        for i, check in enumerate(request.checks, 1):
            content.append(f"  {i}. ", style="dim")
            content.append(f"{check.description}\n", style=risk_color)
            content.append(f"     Suggestion: {check.suggestion}\n", style="dim")

        panel = Panel(
            content,
            title="[bold yellow] COMMAND REQUIRES APPROVAL [/bold yellow]",
            border_style=risk_color,
        )

        console.print()
        console.print(panel)
        console.print("[dim]Options: [Y] Approve  [N] Deny  [S] Show full command  [?] Help[/dim]")
        console.print()

    except ImportError:
        # Fall back to plain text
        print(request.format_simple())

    # Get user input
    while True:
        try:
            # to_thread, not input(): this coroutine runs on the event loop's
            # thread, so a bare input() stops every other task in the process
            # for as long as the prompt is on screen -- timers, sockets,
            # keepalives, cancellations. Only this task should wait.
            raw = await asyncio.to_thread(input, "Approve this command? [Y/N/S/?]: ")
            choice = raw.strip().lower()

            if choice in ("y", "yes"):
                return ApprovalDecision.APPROVED
            elif choice in ("n", "no"):
                return ApprovalDecision.DENIED
            elif choice == "s":
                print(f"\nFull command:\n{request.command}\n")
            elif choice == "?":
                print("\nHelp:")
                print("  Y - Approve and execute the command")
                print("  N - Deny and cancel the command")
                print("  S - Show the full command details")
                print("  ? - Show this help message\n")
            else:
                print("Invalid choice. Enter Y, N, S, or ?")

        except EOFError:
            # Non-interactive environment
            logger.warning("Non-interactive environment, denying by default")
            return ApprovalDecision.DENIED
        except KeyboardInterrupt:
            print("\nCancelled by user")
            return ApprovalDecision.DENIED


async def auto_approve_callback(request: ApprovalRequest) -> ApprovalDecision:
    """Callback that auto-approves everything (use with caution!).

    This is useful for automated testing or trusted environments.
    NEVER use this in production with untrusted agents.

    Args:
        request: The approval request (ignored)

    Returns:
        Always APPROVED
    """
    logger.warning(f"Auto-approving command: {request.command}")
    return ApprovalDecision.APPROVED


async def auto_deny_callback(request: ApprovalRequest) -> ApprovalDecision:
    """Callback that auto-denies everything.

    Useful for dry-run mode or highly restrictive environments.

    Args:
        request: The approval request (logged but not executed)

    Returns:
        Always DENIED
    """
    logger.info(f"Auto-denying command: {request.command}")
    return ApprovalDecision.DENIED
