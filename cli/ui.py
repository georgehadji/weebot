"""CLI Agentic UI — rich.Live streaming for tool calls and reasoning.

Part of Enhancement 6 (Agentic UI).  Uses ``rich.Live`` to display:
- A live tree of the LATS search process
- Streaming tool arguments as they're generated
- Progressive disclosure of reasoning (<think> blocks collapsible)

Usage:
    ui = AgenticUI()
    ui.emit_tool_call("bash", "ls -la /app")
    ui.emit_reasoning("I need to check the auth module...")
    ui.emit_result("3 files found")
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

# rich is optional — graceful fallback to plain logging
try:
    from rich.console import Console
    from rich.live import Live
    from rich.tree import Tree
    from rich.panel import Panel
    from rich.text import Text
    from rich.prompt import Prompt
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


class AgenticUI:
    """Streaming CLI UI for agent reasoning, tool calls, and HITL prompts.

    Uses ``rich.Live`` when available; falls back to plain ``print()`` statements.
    """

    def __init__(self, title: str = "Weebot Agent") -> None:
        self._title = title
        self._tree: Optional[Any] = None
        self._live: Optional[Any] = None
        self._tool_panels: list[Any] = []
        self._console = Console() if _RICH_AVAILABLE else None

    def __enter__(self) -> "AgenticUI":
        if _RICH_AVAILABLE and self._console:
            self._tree = Tree(f"[bold cyan]{self._title}[/bold cyan]")
            self._live = Live(self._tree, console=self._console, refresh_per_second=4)
            self._live.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._live and _RICH_AVAILABLE:
            self._live.__exit__(*args)

    # ── Emitters ─────────────────────────────────────────────────────────

    def emit_reasoning(self, text: str) -> None:
        """Emit a reasoning step (dimmed/think)."""
        if _RICH_AVAILABLE and self._tree is not None:
            self._tree.add(Text(f"💭 {text[:120]}", style="dim"))
            self._refresh()
        else:
            logger.info("[think] %s", text[:200])

    def emit_tool_call(self, tool_name: str, arguments: str) -> None:
        """Emit a tool call with its arguments."""
        if _RICH_AVAILABLE and self._tree is not None:
            panel = Panel(
                Text(f"{tool_name}({arguments[:80]})", style="bold yellow"),
                title=f"🔧 {tool_name}",
                border_style="yellow",
                width=80,
            )
            self._tool_panels.append(panel)
            if len(self._tool_panels) <= 3:
                node = self._tree.add(panel)
            else:
                node = self._tree.add(Text(f"... +{len(self._tool_panels) - 3} more tool calls"))
            self._refresh()
        else:
            logger.info("[tool] %s(%s)", tool_name, arguments[:100])

    def emit_result(self, text: str) -> None:
        """Emit a tool result or observation."""
        if _RICH_AVAILABLE and self._tree is not None:
            self._tree.add(Text(f"✅ {text[:120]}", style="green"))
            self._refresh()
        else:
            logger.info("[result] %s", text[:200])

    def emit_error(self, text: str) -> None:
        """Emit an error message."""
        if _RICH_AVAILABLE and self._tree is not None:
            self._tree.add(Text(f"❌ {text[:120]}", style="bold red"))
            self._refresh()
        else:
            logger.error("[error] %s", text[:200])

    def emit_plan(self, steps: list[str]) -> None:
        """Emit a plan with numbered steps."""
        if _RICH_AVAILABLE and self._tree is not None:
            plan_node = self._tree.add("[bold]📋 Plan[/bold]")
            for i, step in enumerate(steps, 1):
                plan_node.add(Text(f"{i}. {step[:80]}"))
            self._refresh()
        else:
            logger.info("[plan] %d steps", len(steps))

    # ── HITL prompt ──────────────────────────────────────────────────────

    def ask_approval(self, tool: str, args: str, reason: str) -> bool:
        """Ask the user for approval (Tier 3). Returns True if approved."""
        # Non-interactive mode — auto-deny unless WEEBOT_AUTO_APPROVE is set
        if os.getenv("WEEBOT_AUTO_APPROVE") == "1":
            return True
        if not sys.stdin.isatty():
            logger.warning("[HITL] %s(%s) requires approval but stdin is not a TTY — denying", tool, args[:50])
            return False
        if _RICH_AVAILABLE and self._console:
            self._console.print(
                Panel(
                    f"[bold red]⚠️  Tool requires approval[/bold red]\n"
                    f"Tool: {tool}\nArgs: {args}\nReason: {reason}",
                    border_style="red",
                )
            )
            try:
                return Prompt.ask("Approve?", choices=["y", "n"], default="n") == "y"
            except (EOFError, KeyboardInterrupt):
                return False
        else:
            logger.warning("[HITL] %s(%s) requires approval: %s", tool, args[:50], reason)
            return False

    def display_summary(self, text: str) -> None:
        """Display a final summary message."""
        if _RICH_AVAILABLE and self._console:
            self._console.print(Panel(Text(text, style="bold cyan"), title="Summary"))
        else:
            logger.info("[summary] %s", text[:200])

    # ── Internal ─────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """Refresh the live display."""
        if self._live is not None and _RICH_AVAILABLE:
            try:
                self._live.refresh()
            except Exception:
                pass
