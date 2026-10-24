"""Turn a session's stored meta-analysis notes into lines the planner can use."""

from __future__ import annotations

import os


def session_lessons(meta_notes: list[str]) -> list[str]:
    """Notes of this session, newest last, as planner-ready lines (blank ones dropped)."""
    return [f"Lesson from an earlier task in this session: {n}" for n in meta_notes if n and n.strip()]


def project_key(working_dir: object) -> str:
    """Key lessons are filed under: the session's working dir, else the process's.

    Nothing sets ``working_dir`` on a session context, so the old lookups filed
    and read everything under ``""`` or, at one site, raised AttributeError.
    """
    return str(working_dir or os.getcwd())


def journal_lessons(entries: list, session_notes: list[str]) -> list[str]:
    """Lessons filed by earlier sessions of this project, minus those already in this one."""
    seen = {n.strip() for n in session_notes if n}
    return [
        f"Lesson from an earlier session of this project: {e.correction_text}"
        for e in entries
        if e.symptom == "session_lesson" and e.correction_text and e.correction_text.strip() not in seen
    ]
