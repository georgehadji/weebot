"""MCP server entry point for weebot."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

# ── Load .env into os.environ before any weebot module reads API keys ──
# pydantic-settings loads .env into its own store but does NOT populate
# os.environ. Several modules (openai_adapter.py, model_registry/_service.py,
# browser_tool.py, image_gen_tool.py, openrouter_enhanced_cascade.py) read
# keys via bare os.getenv(). Without this call, those paths fall back to a
# stale system/User environment variable instead of the current .env value.
#
# override=True: .env values take priority over stale system environment
# variables (e.g. an old OPENROUTER_API_KEY persisted in the OS profile).
from dotenv import load_dotenv

load_dotenv(override=True)

# Configure structured logging
from weebot.infrastructure.observability.logging_config import (
    configure_logging as _configure_weebot_logging,
)

_configure_weebot_logging()

logger = logging.getLogger(__name__)


def _resolve(label: str, get):
    """*get()*, or None (logged) when that collaborator is not available."""
    try:
        return get()
    except Exception as exc:
        logger.debug("Optional dependency %s unavailable: %s", label, exc)
        return None


def _build_server(container=None):
    """Construct a WeebotMCPServer from one composition-root container (W5.3).

    Each collaborator is optional: one that does not resolve is left out and
    the server runs without it. The scheduler was imported from a module that
    does not exist (weebot.infrastructure.scheduling), so it was always None.
    """
    from weebot.application.ports.event_store_port import EventStorePort
    from weebot.application.ports.rerank_port import RerankPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.config.settings import get_settings
    from weebot.mcp.server import WeebotMCPServer

    if container is None:
        from weebot.application.di import Container

        container = Container()
        container.configure_defaults()
    settings = get_settings()
    return WeebotMCPServer(
        state_manager=_resolve("state repo", lambda: container.get(StateRepositoryPort)),
        scheduler=_resolve("scheduler", container.build_scheduler),
        event_store=_resolve("event store", lambda: container.get(EventStorePort)),
        rerank=_resolve("reranker", lambda: container.get(RerankPort)),
        # Without these, weebot://tools and weebot://skills were stubs (F62).
        tool_discovery=_resolve("tool discovery", lambda: container._create_tool_discovery()),
        skill_registry=_resolve("skill registry", _loaded_skills),
        composite_tools_enabled=settings.mcp_composite_tools_enabled,
    )


def _loaded_skills():
    from weebot.application.skills.skill_registry import SkillRegistry

    registry = SkillRegistry()
    registry.load_all()
    return registry


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
        from weebot.config.settings import get_settings

        get_settings().validate_at_least_one_key()
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

    # When --allow-remote is used, an API key is mandatory
    if args.allow_remote:
        from weebot.config.secret_accessor import SecretAccessor

        _mcp_key = SecretAccessor.get("WEEBOT_MCP_API_KEY")
        if not _mcp_key:
            print(
                "ERROR: --allow-remote requires WEEBOT_MCP_API_KEY to be set. "
                "Remote SSE binding without authentication is not allowed.",
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
