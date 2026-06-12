"""ProductTool -- product backlog and roadmap management.

Stores requirements via ToolRepositoryPort.  Falls back to direct sqlite3
only when no repository is provided (deprecated path).

Author: Georgios-Chrysovalantis Chatzivantsidis
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from pydantic import PrivateAttr

from weebot.application.ports.tool_repository_port import ToolRepositoryPort
from weebot.tools.base import BaseTool, ToolResult

_VALID_CATEGORIES = {"feature", "bug", "tech-debt", "epic"}
_VALID_STATUSES = {"draft", "approved", "in-progress", "done", "rejected"}


class ProductTool(BaseTool):
    """Manage a product requirements backlog and generate PRDs.

    Actions
    -------
    add_requirement   -- Create a new requirement / user story
    list_requirements -- Browse requirements (filter by project/status/priority)
    update_status     -- Advance a requirement through the workflow
    generate_prd      -- Produce a markdown PRD from all approved requirements
    get_roadmap       -- Return a structured JSON roadmap grouped by category
    """

    name: str = "product"
    description: str = (
        "Product backlog manager: add requirements, track status, and generate "
        "PRD documents or JSON roadmaps. "
        "See the 'action' parameter for available operations."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "add_requirement",
                    "list_requirements",
                    "update_status",
                    "generate_prd",
                    "get_roadmap",
                ],
                "description": "Operation to perform.",
            },
            "req_id": {
                "type": "string",
                "description": "Requirement ID (required for update_status).",
            },
            "project_id": {
                "type": "string",
                "description": "Project ID (required for add_requirement, generate_prd, get_roadmap).",
            },
            "title": {
                "type": "string",
                "description": "Short requirement title (required for add_requirement).",
            },
            "description": {
                "type": "string",
                "description": "Detailed requirement description (optional).",
            },
            "category": {
                "type": "string",
                "enum": ["feature", "bug", "tech-debt", "epic"],
                "description": "Requirement category. Default: 'feature'.",
            },
            "priority": {
                "type": "integer",
                "description": "Priority 1 (highest) to 5 (lowest). Default: 3.",
            },
            "status": {
                "type": "string",
                "enum": ["draft", "approved", "in-progress", "done", "rejected"],
                "description": "New status (required for update_status).",
            },
            "tags": {
                "type": "string",
                "description": "Comma-separated tags (optional).",
            },
        },
        "required": ["action"],
    }

    _repo: ToolRepositoryPort = PrivateAttr()

    def __init__(self, repo: ToolRepositoryPort):
        super().__init__()
        self._repo = repo

    # ------------------------------------------------------------------
    # Public execute dispatcher
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            if action == "add_requirement":
                return await self._add_requirement(kwargs)
            if action == "list_requirements":
                return await self._list_requirements(kwargs)
            if action == "update_status":
                return await self._update_status(kwargs)
            if action == "generate_prd":
                return await self._generate_prd(kwargs)
            if action == "get_roadmap":
                return await self._get_roadmap(kwargs)
            return ToolResult(output="", error=f"Unknown action: {action!r}")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))

    # ------------------------------------------------------------------
    # Private action implementations (delegate to ToolRepositoryPort)
    # ------------------------------------------------------------------

    async def _add_requirement(self, kw: dict) -> ToolResult:
        project_id = (kw.get("project_id") or "").strip()
        title = (kw.get("title") or "").strip()
        if not project_id:
            return ToolResult(output="", error="'project_id' is required for add_requirement")
        if not title:
            return ToolResult(output="", error="'title' is required for add_requirement")

        category = kw.get("category") or "feature"
        if category not in _VALID_CATEGORIES:
            return ToolResult(
                output="", error=f"Invalid category {category!r}. Choose from {sorted(_VALID_CATEGORIES)}"
            )

        raw_priority = kw.get("priority")
        try:
            priority_int = int(raw_priority) if raw_priority is not None else 3
        except (TypeError, ValueError):
            priority_int = 3
        priority_int = max(1, min(5, priority_int))
        priority_label = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "trivial"}.get(priority_int, "medium")

        description = (kw.get("description") or "").strip()
        tags = (kw.get("tags") or "").strip()

        # Prepend tags + category to description for storage
        full_description = f"[category: {category}] [tags: {tags}] {description}".strip()

        req_id = await self._repo.save_requirement(
            title=title,
            description=full_description,
            priority=priority_label,
            project_id=project_id,
        )
        return ToolResult(output=json.dumps({"req_id": req_id, "title": title}))

    async def _list_requirements(self, kw: dict) -> ToolResult:
        project_id = kw.get("project_id") or None
        status = kw.get("status") or None
        raw_priority = kw.get("priority")
        priority_label = None
        if raw_priority is not None:
            try:
                p = int(raw_priority)
                priority_label = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "trivial"}.get(p, "medium")
            except (TypeError, ValueError):
                pass

        rows = await self._repo.get_requirements(
            project_id=project_id or "",
            status=status,
            priority=priority_label,
        )
        return ToolResult(
            output=json.dumps({"count": len(rows), "requirements": rows}, indent=2)
        )

    async def _update_status(self, kw: dict) -> ToolResult:
        req_id = (kw.get("req_id") or "").strip()
        status = (kw.get("status") or "").strip()
        if not req_id:
            return ToolResult(output="", error="'req_id' is required for update_status")
        if not status:
            return ToolResult(output="", error="'status' is required for update_status")
        if status not in _VALID_STATUSES:
            return ToolResult(
                output="",
                error=f"Invalid status {status!r}. Choose from {sorted(_VALID_STATUSES)}",
            )

        updated = await self._repo.update_requirement_status(req_id, status)
        if not updated:
            return ToolResult(output="", error=f"Requirement {req_id!r} not found")
        return ToolResult(output=json.dumps({"req_id": req_id, "status": status}))

    async def _generate_prd(self, kw: dict) -> ToolResult:
        project_id = (kw.get("project_id") or "").strip()
        if not project_id:
            return ToolResult(output="", error="'project_id' is required for generate_prd")

        rows = await self._repo.get_requirements(project_id=project_id)
        if not rows:
            return ToolResult(output="", error=f"No requirements found for project {project_id!r}")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        lines = [
            "# Product Requirements Document",
            "",
            f"**Project:** {project_id}  ",
            f"**Generated:** {now}  ",
            f"**Total requirements:** {len(rows)}",
            "",
            "---",
            "",
        ]

        # Group by extracted category from description
        by_category: dict[str, list[dict]] = {}
        for req in rows:
            desc = req.get("description", "")
            cat = "feature"
            if "[category:" in desc:
                import re as _re
                m = _re.search(r"\[category:\s*(\w+)\]", desc)
                if m:
                    cat = m.group(1)
            by_category.setdefault(cat, []).append(req)

        for category, items in sorted(by_category.items()):
            lines.append(f"## {category.title()}")
            lines.append("")
            for req in items:
                # Extract clean description (strip metadata prefix)
                desc = req.get("description", "")
                import re as _re2
                clean_desc = _re2.sub(r"\[.*?\]\s*", "", desc).strip()
                status_badge = f"`{req.get('status', 'open')}`"
                priority_label = f"P{req.get('priority', 'medium')}"
                lines.append(f"### {req.get('id', '?')}: {req.get('title', '')}")
                lines.append(
                    f"**Status:** {status_badge} | **Priority:** {priority_label}"
                    f" | **Category:** {category}"
                )
                lines.append("")
                if clean_desc:
                    lines.append(clean_desc)
                    lines.append("")
                lines.append("---")
                lines.append("")

        return ToolResult(output="\n".join(lines))

    async def _get_roadmap(self, kw: dict) -> ToolResult:
        project_id = (kw.get("project_id") or "").strip()
        if not project_id:
            return ToolResult(output="", error="'project_id' is required for get_roadmap")

        rows = await self._repo.get_requirements(project_id=project_id)

        # Group by extracted category
        by_category: dict[str, list[dict]] = {}
        for req in rows:
            desc = req.get("description", "")
            cat = "feature"
            if "[category:" in desc:
                import re as _re
                m = _re.search(r"\[category:\s*(\w+)\]", desc)
                if m:
                    cat = m.group(1)
            by_category.setdefault(cat, []).append(req)

        roadmap = {
            "project_id": project_id,
            "generated_at": datetime.now().isoformat(),
            "total": len(rows),
            "by_category": by_category,
        }
        return ToolResult(output=json.dumps(roadmap, indent=2))
