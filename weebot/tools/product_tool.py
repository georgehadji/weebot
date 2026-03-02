"""ProductTool -- product backlog and roadmap management.

Stores requirements / user stories in an SQLite table so the agent can
track features, bugs, and tech-debt across sessions.  Includes a markdown
PRD generator and a structured JSON roadmap view.

Author: Georgios-Chrysovalantis Chatzivantsidis
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

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

    db_path: str = "projects.db"

    def model_post_init(self, __context: Any) -> None:
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the requirements table if it does not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS requirements (
                    req_id      TEXT PRIMARY KEY,
                    project_id  TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    category    TEXT DEFAULT 'feature',
                    priority    INTEGER DEFAULT 3,
                    status      TEXT DEFAULT 'draft',
                    tags        TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
            """)
            conn.commit()

    # ------------------------------------------------------------------
    # Public execute dispatcher
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            if action == "add_requirement":
                return self._add_requirement(kwargs)
            if action == "list_requirements":
                return self._list_requirements(kwargs)
            if action == "update_status":
                return self._update_status(kwargs)
            if action == "generate_prd":
                return self._generate_prd(kwargs)
            if action == "get_roadmap":
                return self._get_roadmap(kwargs)
            return ToolResult(output="", error=f"Unknown action: {action!r}")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))

    # ------------------------------------------------------------------
    # Private action implementations
    # ------------------------------------------------------------------

    def _add_requirement(self, kw: dict) -> ToolResult:
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
            priority = int(raw_priority) if raw_priority is not None else 3
        except (TypeError, ValueError):
            priority = 3
        priority = max(1, min(5, priority))

        req_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO requirements
                   (req_id, project_id, title, description, category,
                    priority, status, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)""",
                (
                    req_id,
                    project_id,
                    title,
                    kw.get("description") or "",
                    category,
                    priority,
                    kw.get("tags") or "",
                    now,
                    now,
                ),
            )
            conn.commit()

        return ToolResult(output=json.dumps({"req_id": req_id, "title": title}))

    def _list_requirements(self, kw: dict) -> ToolResult:
        project_id = kw.get("project_id") or None
        status = kw.get("status") or None
        raw_priority = kw.get("priority")
        priority = None
        if raw_priority is not None:
            try:
                priority = int(raw_priority)
            except (TypeError, ValueError):
                pass

        sql = (
            "SELECT req_id, project_id, title, category, priority, status, tags, created_at "
            "FROM requirements"
        )
        params: list = []
        conditions: list[str] = []

        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if priority is not None:
            conditions.append("priority = ?")
            params.append(priority)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY priority ASC, created_at ASC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

        reqs = [dict(r) for r in rows]
        return ToolResult(
            output=json.dumps({"count": len(reqs), "requirements": reqs}, indent=2)
        )

    def _update_status(self, kw: dict) -> ToolResult:
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

        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE requirements SET status = ?, updated_at = ? WHERE req_id = ?",
                (status, now, req_id),
            )
            conn.commit()
            updated = cursor.rowcount

        if updated == 0:
            return ToolResult(output="", error=f"Requirement {req_id!r} not found")
        return ToolResult(output=json.dumps({"req_id": req_id, "status": status}))

    def _generate_prd(self, kw: dict) -> ToolResult:
        project_id = (kw.get("project_id") or "").strip()
        if not project_id:
            return ToolResult(output="", error="'project_id' is required for generate_prd")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT req_id, title, description, category, priority, status, tags
                   FROM requirements
                   WHERE project_id = ?
                   ORDER BY priority ASC, category ASC""",
                (project_id,),
            )
            rows = cursor.fetchall()

        if not rows:
            return ToolResult(
                output="", error=f"No requirements found for project {project_id!r}"
            )

        reqs = [dict(r) for r in rows]
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        lines = [
            f"# Product Requirements Document",
            f"",
            f"**Project:** {project_id}  ",
            f"**Generated:** {now}  ",
            f"**Total requirements:** {len(reqs)}",
            f"",
            f"---",
            f"",
        ]

        # Group by category
        by_category: dict[str, list[dict]] = {}
        for req in reqs:
            by_category.setdefault(req["category"], []).append(req)

        for category, items in sorted(by_category.items()):
            lines.append(f"## {category.title()}")
            lines.append("")
            for req in items:
                status_badge = f"`{req['status']}`"
                priority_label = f"P{req['priority']}"
                tags = f" | **Tags:** {req['tags']}" if req["tags"] else ""
                lines.append(f"### {req['req_id']}: {req['title']}")
                lines.append(
                    f"**Status:** {status_badge} | **Priority:** {priority_label}"
                    f" | **Category:** {req['category']}{tags}"
                )
                lines.append("")
                if req["description"]:
                    lines.append(req["description"])
                    lines.append("")
                lines.append("---")
                lines.append("")

        return ToolResult(output="\n".join(lines))

    def _get_roadmap(self, kw: dict) -> ToolResult:
        project_id = (kw.get("project_id") or "").strip()
        if not project_id:
            return ToolResult(output="", error="'project_id' is required for get_roadmap")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT req_id, title, category, priority, status, tags
                   FROM requirements
                   WHERE project_id = ?
                   ORDER BY priority ASC, category ASC""",
                (project_id,),
            )
            rows = cursor.fetchall()

        reqs = [dict(r) for r in rows]

        # Group by category
        by_category: dict[str, list[dict]] = {}
        for req in reqs:
            by_category.setdefault(req["category"], []).append(req)

        roadmap = {
            "project_id": project_id,
            "generated_at": datetime.now().isoformat(),
            "total": len(reqs),
            "by_category": by_category,
        }
        return ToolResult(output=json.dumps(roadmap, indent=2))
