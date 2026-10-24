"""Turn a session's stored meta-analysis notes into lines the planner can use."""

from __future__ import annotations


def session_lessons(meta_notes: list[str]) -> list[str]:
    """Notes of this session, newest last, as planner-ready lines (blank ones dropped)."""
    return [f"Lesson from an earlier task in this session: {n}" for n in meta_notes if n and n.strip()]
