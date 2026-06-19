"""MCPToolSkillIndexer — auto-indexes MCP server tools as retrievable skills.

Runs once after MCP bridge initialization.  Converts each discovered tool
into a lightweight ``Skill`` domain object and registers it in the
``SkillRegistry`` so the semantic retriever can surface MCP tools for
relevant queries.

MCP-derived skills are tagged ``provenance="imported"`` and
``trust="candidate"`` — they follow the existing trust promotion pipeline
(``Skill.record_positive_use()`` accumulates uses; after
``CANDIDATE_PROMOTION_USES`` validated uses, the curator can promote to
``trusted`` for live injection).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from weebot.application.skills.skill_registry import SkillRegistry
from weebot.domain.models.skill import Skill, SkillMetadata, SkillProvenance

logger = logging.getLogger(__name__)

# Prefix to distinguish MCP-derived skills from filesystem ones.
# Stripped on display; used internally to avoid name collisions.
MCP_SKILL_PREFIX = "mcp:"


class MCPToolSkillIndexer:
    """Indexes MCP bridge tools into the skill registry.

    Call ``index_tools()`` after the bridge is initialized.  Idempotent —
    re-running updates existing entries rather than duplicating, because
    ``SkillRegistry.update_skill()`` replaces by name.

    Args:
        registry: The application-level ``SkillRegistry`` instance.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    async def index_tools(self, bridge) -> int:
        """Index all tools from *bridge* (an ``MCPToolBridge``) into the registry.

        Args:
            bridge: An initialized ``MCPToolBridge`` instance with
                    ``get_tools()`` returning ``list[BaseTool]``.

        Returns:
            Number of tools indexed.
        """
        tools = await bridge.get_tools()
        count = 0

        for tool in tools:
            name = f"{MCP_SKILL_PREFIX}{tool.name}"
            desc = getattr(tool, "description", "") or f"MCP tool: {tool.name}"
            self._index_single(name, desc)
            count += 1

        if count:
            logger.info("MCPToolSkillIndexer: indexed %d tools", count)
        return count

    async def index_tool_infos(self, tool_infos: list, server_name: str) -> int:
        """Index MCP tools from ``MCPToolInfo`` objects (``MCPToolRegistryBridge`` path).

        Args:
            tool_infos: List of ``MCPToolInfo`` objects with ``namespaced_name``,
                        ``description``, and ``original_name`` attributes.
            server_name: The MCP server these tools belong to.

        Returns:
            Number of tools indexed.
        """
        count = 0
        for info in tool_infos:
            name = f"{MCP_SKILL_PREFIX}{info.namespaced_name}"
            desc = getattr(info, "description", "") or info.original_name
            self._index_single(name, desc)
            count += 1
        if count:
            logger.info(
                "MCPToolSkillIndexer: indexed %d tools from server '%s'",
                count, server_name,
            )
        return count

    # ── Helpers ────────────────────────────────────────────────────

    def _index_single(self, name: str, desc: str) -> None:
        """Create and register a single MCP-derived skill (idempotent)."""
        # Skip tools that are already indexed (idempotent)
        existing = self._registry.get(name)
        if existing is not None:
            return

        skill = Skill(
            name=name,
            description=desc,
            content=desc,  # description is the primary embedding signal
            metadata=SkillMetadata(
                trust="candidate",
                provenance=SkillProvenance(
                    origin="imported",
                    created_at=datetime.now(timezone.utc),
                ),
            ),
        )
        self._registry.update_skill(skill)
