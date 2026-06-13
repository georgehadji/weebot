"""MCP server entry point for weebot."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import sys

logger = logging.getLogger(__name__)


def _try_attach(module_path: str, class_name: str, label: str) -> object | None:
    """Import *class_name* from *module_path*, return an instance or None on failure."""
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls()
    except Exception as exc:
        logger.debug("Optional dependency %s unavailable: %s", label, exc)
        return None


def _build_server():
    """Construct a WeebotMCPServer with optional managers attached."""
    from weebot.mcp.server import WeebotMCPServer

    state_manager = _try_attach(
        "weebot.infrastructure.persistence.sqlite_state_repo",
        "StateManager",
        "StateManager",
    )
    scheduler = _try_attach(
        "weebot.infrastructure.scheduling.scheduler",
        "SchedulingManager",
        "SchedulingManager",
    )
    return WeebotMCPServer(state_manager=state_manager, scheduler=scheduler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Weebot MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="SSE bind host")
    parser.add_argument("--port", type=int, default=8765, help="SSE bind port")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow non-loopback SSE binding (security opt-in required)",
    )
    args = parser.parse_args()

    # Validate settings
    try:
        from weebot.config.settings import WeebotSettings
        WeebotSettings.validate_at_least_one_key()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Guard against accidental remote SSE exposure
    _loopback = {"127.0.0.1", "::1", "localhost"}
    if args.transport == "sse" and args.host not in _loopback and not args.allow_remote:
        print(
            f"ERROR: Binding SSE to {args.host!r} exposes the server to the network. "
            "Pass --allow-remote to opt in explicitly.",
            file=sys.stderr,
        )
        sys.exit(2)

    server = _build_server()

    if args.transport == "sse":
        asyncio.run(server.run_sse(host=args.host, port=args.port))
    else:
        asyncio.run(server.run_stdio())


if __name__ == "__main__":
    main()
