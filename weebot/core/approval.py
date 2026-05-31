"""Approval workflow for risky operations.

This module provides an approval workflow for commands that are flagged
as suspicious or dangerous by the BashGuard.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Coroutine, Optional

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
    session_id: Optional[str] = None
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
            "║ Safety Concerns:{'':<62} ║",
        ]

        for check in self.checks:
            lines.append(f"║   • {check.description[:72]:<72} ║")
            lines.append(f"║     Suggestion: {check.suggestion[:59]:<59} ║")

        lines.extend([
            "╠" + "═" * 78 + "╣",
            "║ Options: [Y] Approve  [N] Deny  [S] Show details  [?] Help{'':<26} ║",
            "╚" + "═" * 78 + "╝",
            "",
        ])

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

        lines.extend([
            "",
            "Options: Y = Approve, N = Deny",
            "=" * 60,
            "",
        ])

        return "\n".join(lines)


# Type alias for approval callback
ApprovalCallback = Callable[[ApprovalRequest], Coroutine[None, None, ApprovalDecision]]


class ApprovalManager:
    """Manages approval workflow for risky commands.

    This class handles the approval workflow, including:
    - Auto-approving safe commands
    - Blocking blocked commands
    - Requesting approval for suspicious/dangerous commands
    - Caching approval decisions per session

    Example:
        >>> manager = ApprovalManager(auto_approve_safe=True)
        >>> request = ApprovalRequest(
        ...     command="rm -rf build/",
        ...     risk_level=RiskLevel.DANGEROUS,
        ...     checks=[...]
        ... )
        >>> decision = await manager.request_approval(request)
    """

    def __init__(
        self,
        auto_approve_safe: bool = True,
        auto_deny_blocked: bool = True,
        approval_callback: Optional[ApprovalCallback] = None,
    ):
        """Initialize the ApprovalManager.

        Args:
            auto_approve_safe: Whether to auto-approve SAFE commands
            auto_deny_blocked: Whether to auto-deny BLOCKED commands
            approval_callback: Optional callback for approval requests
        """
        self.auto_approve_safe = auto_approve_safe
        self.auto_deny_blocked = auto_deny_blocked
        self._approval_callback = approval_callback
        self._session_approvals: dict[str, ApprovalDecision] = {}
        self._session_whitelist: dict[str, list[str]] = {}  # session -> list of approved commands
        self._max_sessions = 50  # Evict oldest session when exceeded

    def set_approval_callback(self, callback: ApprovalCallback) -> None:
        """Set the callback for approval requests.

        The callback will be called when user approval is needed.
        It should return an ApprovalDecision.

        Args:
            callback: Async function that takes ApprovalRequest and returns Decision
        """
        self._approval_callback = callback

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Request approval for a command.

        This method handles the approval logic:
        1. Auto-approve SAFE commands (if enabled)
        2. Auto-deny BLOCKED commands (if enabled)
        3. Check session whitelist
        4. Call approval callback for SUSPICIOUS/DANGEROUS

        Args:
            request: The approval request

        Returns:
            ApprovalDecision
        """
        # Auto-approve safe commands
        if request.risk_level == RiskLevel.SAFE and self.auto_approve_safe:
            logger.debug(f"Auto-approved safe command: {request.command}")
            return ApprovalDecision.APPROVED

        # Auto-deny blocked commands
        if request.risk_level == RiskLevel.BLOCKED and self.auto_deny_blocked:
            logger.warning(f"Auto-denied blocked command: {request.command}")
            return ApprovalDecision.DENIED

        # Check session-level pre-approval
        if request.session_id:
            # Check if entire session is approved/denied
            if request.session_id in self._session_approvals:
                decision = self._session_approvals[request.session_id]
                logger.debug(f"Using cached session decision: {decision}")
                return decision

            # Check if this specific command was approved
            whitelist = self._session_whitelist.get(request.session_id, [])
            if request.command in whitelist:
                logger.debug(f"Command in session whitelist: {request.command}")
                return ApprovalDecision.APPROVED

        # Request approval via callback
        if self._approval_callback:
            try:
                decision = await self._approval_callback(request)
                logger.info(f"Approval callback returned: {decision}")
                return decision
            except Exception as e:
                logger.error(f"Approval callback failed: {e}")
                # Fail secure: deny on error
                return ApprovalDecision.DENIED

        # No callback set - fail secure
        logger.warning("No approval callback set, denying by default")
        return ApprovalDecision.DENIED

    def approve_for_session(
        self, session_id: str, decision: ApprovalDecision = ApprovalDecision.APPROVED
    ) -> None:
        """Pre-approve all commands for a session.

        Args:
            session_id: The session to approve
            decision: The decision to apply (default: APPROVED)
        """
        # Evict oldest session when at capacity
        if session_id not in self._session_approvals and len(self._session_approvals) >= self._max_sessions:
            oldest = next(iter(self._session_approvals))
            del self._session_approvals[oldest]
            self._session_whitelist.pop(oldest, None)
        self._session_approvals[session_id] = decision
        logger.info(f"Set session {session_id} approval to: {decision}")

    def approve_command_for_session(self, session_id: str, command: str) -> None:
        """Add a specific command to the session whitelist.

        Args:
            session_id: The session
            command: The command to whitelist
        """
        if session_id not in self._session_whitelist:
            self._session_whitelist[session_id] = []
        if command not in self._session_whitelist[session_id]:
            self._session_whitelist[session_id].append(command)
        logger.debug(f"Added command to session {session_id} whitelist: {command}")

    def clear_session_approvals(self, session_id: str) -> None:
        """Clear all approvals for a session.

        Args:
            session_id: The session to clear
        """
        self._session_approvals.pop(session_id, None)
        self._session_whitelist.pop(session_id, None)
        logger.info(f"Cleared all approvals for session: {session_id}")

    def is_approved(self, session_id: str, command: str) -> bool:
        """Check if a command is approved for a session.

        Args:
            session_id: The session
            command: The command to check

        Returns:
            True if approved
        """
        # Check session-level approval
        if session_id in self._session_approvals:
            return self._session_approvals[session_id] == ApprovalDecision.APPROVED

        # Check whitelist
        whitelist = self._session_whitelist.get(session_id, [])
        return command in whitelist


# Global default instance
default_approval_manager = ApprovalManager()


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
        content.append(
            request.risk_level.value.upper(),
            style=f"bold {risk_color}"
        )
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
            choice = input("Approve this command? [Y/N/S/?]: ").strip().lower()

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


def auto_approve_callback(request: ApprovalRequest) -> ApprovalDecision:
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


def auto_deny_callback(request: ApprovalRequest) -> ApprovalDecision:
    """Callback that auto-denies everything.

    Useful for dry-run mode or highly restrictive environments.

    Args:
        request: The approval request (logged but not executed)

    Returns:
        Always DENIED
    """
    logger.info(f"Auto-denying command: {request.command}")
    return ApprovalDecision.DENIED
