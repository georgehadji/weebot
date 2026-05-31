"""SkillEdit — atomic operations on a skill document.

Four operations with the paper's controllability guarantees:
  append       — add content at the end
  insert_after — insert content after a section anchor
  replace      — replace the content of a section
  delete       — remove a section entirely

Each edit records support_count and source_type so the ranking engine
can prefer edits that survive independent analyses.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field


# Sentinel markers for the protected slow-update section.
SLOW_UPDATE_START = "<!-- SLOW_UPDATE_START -->"
SLOW_UPDATE_END = "<!-- SLOW_UPDATE_END -->"


class SkillEdit(BaseModel):
    """One atomic operation on a skill document.

    Attributes:
        op: The type of edit to perform.
        target: Section header or line anchor (required for insert_after,
            replace, delete).  Ignored for append.
        content: Markdown content to insert or replace with.
        support_count: How many trajectory analyses support this edit.
        source_type: Whether this edit was derived from failure or success analysis.
    """

    op: Literal["append", "insert_after", "replace", "delete"]
    target: Optional[str] = Field(
        default=None,
        description="Section header / line anchor (required for insert_after, replace, delete)",
    )
    content: str = Field(default="", description="Markdown content")
    support_count: int = Field(default=1, ge=1)
    source_type: Literal["failure", "success"] = Field(default="failure")

    def apply_to(self, skill_content: str) -> str:
        """Return *skill_content* with this edit applied.

        Raises ValueError if the edit targets the protected slow-update section,
        or if the target anchor is missing and required.
        """
        self._validate_target_protected(skill_content)

        if self.op == "append":
            return skill_content.rstrip() + "\n\n" + self.content

        if not self.target:
            raise ValueError(f"'{self.op}' requires a target anchor")

        if self.op == "insert_after":
            return self._insert_after(skill_content)

        if self.op == "replace":
            return self._replace_section(skill_content)

        if self.op == "delete":
            return self._delete_section(skill_content)

        return skill_content

    # ── private helpers ──────────────────────────────────────────────

    def _validate_target_protected(self, content: str) -> None:
        """Reject edits targeting the SLOW_UPDATE section."""
        if not self.target:
            return
        slow_start = content.find(SLOW_UPDATE_START)
        slow_end = content.find(SLOW_UPDATE_END)
        if slow_start == -1 or slow_end == -1:
            return
        target_idx = content.find(self.target, slow_start)
        if slow_start <= target_idx <= slow_end + len(SLOW_UPDATE_END):
            raise ValueError(
                f"Cannot edit protected slow-update section: target='{self.target}'"
            )

    def _insert_after(self, content: str) -> str:
        idx = content.find(self.target)
        if idx == -1:
            raise ValueError(f"Target anchor not found: '{self.target}'")
        line_end = content.find("\n", idx)
        insert_at = line_end + 1 if line_end != -1 else len(content)
        return content[:insert_at] + "\n" + self.content + "\n" + content[insert_at:]

    def _replace_section(self, content: str) -> str:
        pattern = rf"^{re.escape(self.target)}.*?(?=\n#|\n---|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError(f"Section header not found: '{self.target}'")
        return content[:match.start()] + self.content + content[match.end():]

    def _delete_section(self, content: str) -> str:
        pattern = rf"^{re.escape(self.target)}.*?(?=\n#|\n---|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError(f"Section header not found: '{self.target}'")
        return content[:match.start()] + content[match.end():]


class SkillEditApplied(BaseModel):
    """Record of an edit that was applied (audit trail entry)."""
    op: Literal["append", "insert_after", "replace", "delete"]
    target: Optional[str] = None
    content: str = ""
    support_count: int = 1
    source_type: Literal["failure", "success"] = "failure"
    accepted: bool = False
    score_delta: Optional[float] = None
