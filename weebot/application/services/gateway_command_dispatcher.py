"""Gateway Command Dispatcher — parses and handles slash commands from gateway messages.

Slash commands allow users to control the agent without going through the
LLM flow.  Commands are parsed from the beginning of gateway messages and,
if recognized, dispatched to the appropriate handler without invoking the flow.

Supported commands:
    /new       — Start a new session (discard current context)
    /reset     — Reset the current session
    /resume    — Resume the last active session (if any)
    /stop      — Stop the current flow execution
    /model     — Show or set the current model
    /tools     — List available tools for the current role
    /help      — Show available commands
    /mcp       — Show MCP server status
    /compress  — Force context compression
"""

from __future__ import annotations

import logging
import shlex
from collections.abc import Callable

from weebot.domain.models.gateway_command import (
    CommandResult,
    Compress,
    ListTools,
    McpStatus,
    NewSession,
    Reply,
    ResumeSession,
    SetModel,
    StopRun,
)

logger = logging.getLogger(__name__)


class GatewayCommandDispatcher:
    """Parses and dispatches gateway slash commands.

    Register command handlers via ``register()``, then call ``dispatch()``
    to parse a message and route to the matching handler.
    """

    def __init__(self) -> None:
        self._commands: dict[str, Callable[..., CommandResult | str]] = {}

    def register(
        self, command: str, handler: Callable[..., CommandResult | str] | None = None
    ) -> Callable | None:
        """Register a handler for *command* (without the leading /).

        Can be used as a decorator: @dispatcher.register("help")
        Or directly: dispatcher.register("help", my_handler)

        Args:
            command: Command name (e.g. "help", "new")
            handler: Callable that takes optional args and returns a CommandResult (a plain
                string counts as ``Reply``).

        Returns:
            The handler if used as a decorator, None otherwise.
        """
        normalized = command.lower().strip()

        def _register(h: Callable[..., CommandResult | str]) -> Callable[..., CommandResult | str]:
            self._commands[normalized] = h
            logger.debug("Registered gateway command: /%s", normalized)
            return h

        if handler is not None:
            _register(handler)
            return None
        return _register

    def is_command(self, text: str) -> bool:
        """Check if *text* starts with a known slash command."""
        if not text or not text.startswith("/"):
            return False
        cmd, _, _ = self._parse(text)
        return cmd in self._commands

    def dispatch(self, text: str) -> CommandResult | None:
        """Parse *text* and dispatch to the matching command handler.

        Args:
            text: The raw message text from the user.

        Returns:
            The handler's CommandResult, or None if the command is unknown.
        """
        if not text or not text.startswith("/"):
            return None

        cmd, args, raw_rest = self._parse(text)
        handler = self._commands.get(cmd)
        if handler is None:
            return None

        try:
            result = handler(*args) if args else handler()
        except Exception as exc:
            logger.error("Command /%s failed: %s", cmd, exc)
            return Reply(f"Command /{cmd} failed: {exc}")
        return Reply(result) if isinstance(result, str) else result

    @staticmethod
    def _parse(text: str) -> tuple[str, list[str], str]:
        """Parse a slash command into (command_name, args_list, raw_rest).

        Example:
            "/model set gpt-4" → ("model", ["set", "gpt-4"], "set gpt-4")
        """
        text = text.strip()
        if not text.startswith("/"):
            return ("", [], text)

        try:
            parts = shlex.split(text)
        except ValueError:  # an unbalanced quote, as in "/what's up" (R21)
            parts = text.split()
        cmd = parts[0][1:].lower()  # Strip leading /
        args = parts[1:] if len(parts) > 1 else []
        raw_rest = text[len(parts[0]) :].strip()
        return (cmd, args, raw_rest)

    def list_commands(self) -> dict[str, str]:
        """Return registered commands (name -> handler doc snippet)."""
        return {f"/{k}": getattr(v, "__doc__", "") or "" for k, v in self._commands.items()}


def build_default_dispatcher() -> GatewayCommandDispatcher:
    """Create a GatewayCommandDispatcher with the standard commands registered.

    The handlers return CommandResult values; each gateway adapter maps a type to an action.
    """
    dispatcher = GatewayCommandDispatcher()

    @dispatcher.register("help")
    def _help() -> CommandResult:
        """Show available commands."""
        return Reply(
            "Available commands:\n"
            "/new     — Start a new conversation session\n"
            "/reset   — Reset the current session\n"
            "/resume  — Resume the last active session\n"
            "/stop    — Stop the current task\n"
            "/model   — Show or set the model\n"
            "/tools   — List available tools\n"
            "/mcp     — Show MCP server status\n"
            "/compress— Force context compression\n"
            "/help    — Show this message"
        )

    @dispatcher.register("new")
    def _new() -> CommandResult:
        """Start a new conversation session."""
        return NewSession()

    @dispatcher.register("reset")
    def _reset() -> CommandResult:
        """Reset the current session."""
        return NewSession()

    @dispatcher.register("resume")
    def _resume() -> CommandResult:
        """Resume the last active session."""
        return ResumeSession()

    @dispatcher.register("stop")
    def _stop() -> CommandResult:
        """Stop the current task execution."""
        return StopRun()

    @dispatcher.register("model")
    def _model(*args: str) -> CommandResult:
        """Show or set the current model.
        Usage: /model [set <model_name>]
        """
        if args and args[0] == "set" and len(args) > 1:
            return SetModel(args[1])
        from weebot.config.model_refs import MODEL_DI_DEFAULT

        return Reply(f"Current model: {MODEL_DI_DEFAULT}")

    @dispatcher.register("tools")
    def _tools() -> CommandResult:
        """List available tools for the current role."""
        return ListTools()

    @dispatcher.register("mcp")
    def _mcp_status(*args: str) -> CommandResult:
        """Show MCP server status.
        Usage: /mcp
        """
        return McpStatus()

    @dispatcher.register("compress")
    def _compress() -> CommandResult:
        """Force context compression."""
        return Compress()

    return dispatcher
