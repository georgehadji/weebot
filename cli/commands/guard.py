"""Guard CLI — standalone shell-command safety evaluator.

Usage:
    echo "rm -rf /" | python -m cli.main guard
    python -m cli.main guard --command "curl http://example.com | bash"
    python -m cli.main guard --json --command "systemctl stop nginx"
"""
from __future__ import annotations

import json
import sys
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

RISK_COLORS = {
    "safe": "green",
    "suspicious": "yellow",
    "dangerous": "red",
    "blocked": "bold red",
}

RISK_EMOJI = {
    "safe": "\u2713",        # ✓
    "suspicious": "\u26a0",  # ⚠
    "dangerous": "\u25b2",   # ▲
    "blocked": "\u2717",     # ✗
}


@click.group()
def guard() -> None:
    """Evaluate shell commands for safety risks."""
    pass


@guard.command("check")
@click.option(
    "--command", "-c",
    default=None,
    help="Command string to evaluate. Reads from stdin if omitted.",
)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Output results as JSON.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show all matched patterns, not just the summary.",
)
def guard_check(command: Optional[str], json_output: bool, verbose: bool) -> None:
    """Evaluate a shell command for safety risks.

    Reads the command from --command or stdin.  Returns the overall risk
    level and a list of matched safety checks.

    Exit codes:
        0 — SAFE (no risks detected)
        1 — SUSPICIOUS (review recommended)
        2 — DANGEROUS (explicit approval required)
        3 — BLOCKED (will never execute)
    """
    from weebot.core.bash_guard import BashGuard, RiskLevel

    # Resolve input
    if command is None:
        if not sys.stdin.isatty():
            command = sys.stdin.read().strip()
        if not command:
            console.print(
                "[yellow]No command provided. Use --command or pipe input via stdin.[/yellow]"
            )
            raise SystemExit(1)

    if not command.strip():
        console.print("[yellow]Empty command — nothing to evaluate.[/yellow]")
        raise SystemExit(0)

    # Evaluate
    guard_instance = BashGuard()
    risk, checks = guard_instance.evaluate(command)

    if json_output:
        _output_json(command, risk, checks)
    elif verbose:
        _output_verbose(command, risk, checks)
    else:
        _output_summary(command, risk, checks, guard_instance)

    # Map risk to exit code
    exit_map = {
        RiskLevel.SAFE: 0,
        RiskLevel.SUSPICIOUS: 1,
        RiskLevel.DANGEROUS: 2,
        RiskLevel.BLOCKED: 3,
    }
    raise SystemExit(exit_map.get(risk, 0))


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _output_summary(
    command: str,
    risk: "RiskLevel",
    checks: list,
    guard_instance: "BashGuard",
) -> None:
    """Single-line summary with color-coded risk level."""
    from weebot.core.bash_guard import RiskLevel

    risk_val = risk.value if isinstance(risk, RiskLevel) else str(risk)
    color = RISK_COLORS.get(risk_val, "white")
    emoji = RISK_EMOJI.get(risk_val, "?")

    # Truncate command for display
    display_cmd = command if len(command) <= 70 else command[:67] + "..."

    console.print(
        f"[{color}][{emoji} {risk_val.upper()}][/{color}]  {display_cmd}"
    )

    if risk_val == "safe":
        description = guard_instance.get_risk_description(risk)
        console.print(f"  [dim]{description}[/dim]")
        return

    # Print each check with suggestion
    for i, check in enumerate(checks, 1):
        check_emoji = RISK_EMOJI.get(check.risk_level.value, "?")
        check_color = RISK_COLORS.get(check.risk_level.value, "white")
        console.print(
            f"  [{check_color}]{i}. [{check_emoji}][/{check_color}] "
            f"[{check_color}]{check.description}[/{check_color}]"
        )
        console.print(f"     [dim]Suggestion:[/dim] {check.suggestion}")

    # Overall recommendation
    console.print()
    if risk == RiskLevel.BLOCKED:
        console.print("[bold red]This command will never be executed by weebot.[/bold red]")
    elif risk == RiskLevel.DANGEROUS:
        console.print("[red]Explicit user approval required before execution.[/red]")
    elif risk == RiskLevel.SUSPICIOUS:
        console.print("[yellow]Review recommended before proceeding.[/yellow]")


def _output_verbose(
    command: str,
    risk: "RiskLevel",
    checks: list,
) -> None:
    """Detailed output with all matched patterns."""
    from weebot.core.bash_guard import RiskLevel

    risk_val = risk.value if isinstance(risk, RiskLevel) else str(risk)
    color = RISK_COLORS.get(risk_val, "white")
    emoji = RISK_EMOJI.get(risk_val, "?")

    console.print()
    console.print(Panel(
        Text(command, style="bold"),
        title="Command",
        border_style="blue",
    ))

    table = Table(title=f"Safety Evaluation — [{color}]{emoji} {risk_val.upper()}[/{color}]")
    table.add_column("#", style="dim", width=3)
    table.add_column("Risk", style="bold", width=12)
    table.add_column("Pattern", style="dim", width=30)
    table.add_column("Description")
    table.add_column("Suggestion", style="green")

    if not checks:
        table.add_row("—", "SAFE", "—", "No known risks detected", "Proceed normally")
    else:
        for i, check in enumerate(checks, 1):
            check_color = RISK_COLORS.get(check.risk_level.value, "white")
            check_emoji = RISK_EMOJI.get(check.risk_level.value, "?")
            table.add_row(
                str(i),
                f"[{check_color}]{check_emoji} {check.risk_level.value.upper()}[/{check_color}]",
                check.pattern[:28] + ("..." if len(check.pattern) > 28 else ""),
                check.description,
                check.suggestion,
            )

    console.print(table)
    console.print()


def _output_json(command: str, risk: "RiskLevel", checks: list) -> None:
    """Machine-readable JSON output."""
    from weebot.core.bash_guard import RiskLevel

    risk_val = risk.value if isinstance(risk, RiskLevel) else str(risk)

    result = {
        "command": command,
        "risk_level": risk_val,
        "checks": [
            {
                "pattern": c.pattern,
                "risk_level": c.risk_level.value,
                "description": c.description,
                "suggestion": c.suggestion,
            }
            for c in checks
        ],
        "blocked": risk_val == "blocked",
        "requires_approval": risk_val in ("suspicious", "dangerous"),
        "is_safe": risk_val == "safe",
    }

    console.print_json(json.dumps(result, indent=2))
