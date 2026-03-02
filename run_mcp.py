#!/usr/bin/env python3
"""run_mcp.py — Standalone MCP server entry point for weebot.

Usage (Claude Desktop — stdio transport, default):
    python run_mcp.py

Usage (Claude IDE / web clients — SSE transport):
    python run_mcp.py --transport sse
    python run_mcp.py --transport sse --host 127.0.0.1 --port 8765

Environment variables:
    See .env.example or weebot/config/settings.py.
    At least one of OPENAI_API_KEY, ANTHROPIC_API_KEY, KIMI_API_KEY,
    or DEEPSEEK_API_KEY must be set.

IMPORTANT — stdio transport:
    stdout is reserved *exclusively* for the MCP protocol (JSON-RPC frames).
    All log output goes to logs/mcp.log.  Never print to stdout.
    Stderr is safe and is used only for fatal startup errors.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Logging — write to a file, NEVER to stdout.
# In stdio mode stdout carries the binary MCP protocol; stray text breaks
# the connection.  Stderr is safe (Claude Desktop does not read it).
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(_LOG_DIR / "mcp.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("weebot.run_mcp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_attach(module_path: str, class_name: str, label: str) -> Optional[Any]:
    """Import *module_path* and instantiate *class_name*; return None on failure.

    Allows the MCP server to start in minimal environments where optional
    managers (StateManager, SchedulerTool) are unavailable.
    """
    try:
        mod = __import__(module_path, fromlist=[class_name])
        cls = getattr(mod, class_name)
        instance = cls()
        logger.info("%s attached to MCP server", label)
        return instance
    except Exception as exc:
        logger.warning("%s not available — %s", label, exc)
        return None


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def _build_server(host: str = "127.0.0.1", port: int = 8765) -> "WeebotMCPServer":
    """Construct WeebotMCPServer and attach live managers where available.

    Both *state_manager* and *scheduler* are attached only when their
    respective modules are importable without errors.  Failures are logged
    and silently ignored so the server always starts in minimal environments.
    """
    from weebot.mcp.server import WeebotMCPServer  # local import keeps module fast to import

    state_manager = _try_attach("weebot.state_manager", "StateManager", "StateManager")
    scheduler = _try_attach("weebot.tools.scheduler", "SchedulerTool", "SchedulerTool")

    return WeebotMCPServer(
        state_manager=state_manager,
        scheduler=scheduler,
        host=host,
        port=port,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="run_mcp",
        description=(
            "weebot MCP server — connects Claude Desktop or Claude IDE "
            "to weebot tools (bash, python_execute, web_search, file_editor, ping)."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help=(
            "Transport protocol.  'stdio' (default) is for Claude Desktop; "
            "'sse' is for Claude IDE and other HTTP/SSE clients."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for SSE transport (ignored in stdio mode). Default: 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (ignored in stdio mode). Default: 8765",
    )
    args = parser.parse_args()

    # --- Fail-fast settings validation ------------------------------------
    # Errors go to stderr — safe in both stdio and SSE modes.
    try:
        from weebot.config.settings import WeebotSettings

        settings = WeebotSettings()
        settings.validate_at_least_one_key()
        logger.info(
            "weebot settings valid — providers: %s",
            ", ".join(settings.available_providers()),
        )
    except Exception as exc:
        print(f"[weebot] Configuration error: {exc}", file=sys.stderr)
        print(
            "[weebot] Set at least one API key in .env or as an environment variable:\n"
            "         OPENAI_API_KEY, ANTHROPIC_API_KEY, KIMI_API_KEY, DEEPSEEK_API_KEY",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Build and run the server -----------------------------------------
    server = _build_server(host=args.host, port=args.port)

    if args.transport == "stdio":
        logger.info("Starting weebot MCP server — stdio transport")
        asyncio.run(server.run_stdio())
    else:
        logger.info(
            "Starting weebot MCP server — SSE transport on %s:%d",
            args.host,
            args.port,
        )
        asyncio.run(server.run_sse())


if __name__ == "__main__":
    main()
