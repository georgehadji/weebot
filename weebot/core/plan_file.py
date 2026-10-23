"""The plan under review as an editable file (ICM B2: every output is an edit surface).

Plan review writes `Output/<session>/01_plan.md`, one numbered line per step.
On approve, FlowRouter reads it back: an edited step list is the plan that
runs. The file is a view for the human; SQLite stays the system of record.
"""

from __future__ import annotations

import re
from pathlib import Path

from weebot.core.output_path import output_path

_STEP = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")


def path_for(session_id: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", session_id)[:80] or "session"
    return Path(output_path(f"Output/{safe}/01_plan.md"))


def write(session_id: str, title: str, steps: list[str]) -> str:
    """Write the plan; return its path."""
    path = path_for(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    path.write_text(
        f"# {title or 'Plan'}\n\n"
        "Edit, add or delete numbered steps, save, then approve. Only the numbered\n"
        "lines are read.\n\n" + body + "\n",
        encoding="utf-8",
    )
    return str(path)


def read_steps(session_id: str) -> list[str] | None:
    """The numbered steps in the file, or None if there is no file."""
    path = path_for(session_id)
    if not path.is_file():
        return None
    steps = [m.group(1) for line in path.read_text(encoding="utf-8").splitlines()
             if (m := _STEP.match(line))]
    return steps or None
