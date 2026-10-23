"""Fail when a verified map card cites a file or line that is not there (ICM A3).

Cards under map/objects/ cite source as `path` or `path:line[-line]`. A
verified card that is silently wrong costs more than a missing one, so this
checks every citation in every `status: verified` card:

- the path resolves to a tracked file (as written, under weebot/, or as the
  unique tracked file ending with it, since cards use short forms);
- a cited line is within the file.

It does not check that the line still says what the card claims; re-verify
cards against source for that (map/_meta/schema.md).

Usage: python scripts/check_map_citations.py   (exit 1 on any broken citation)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CITE = re.compile(
    r"`([\w./\\\-\[\]]+\.(?:py|tsx|ts|mjs|json|toml|yml|yaml))(?::(\d+)(?:[-,]\s?(\d+))?)?"
)


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def _resolve(path: str, tracked: list[str], tracked_set: set[str]) -> str | None:
    path = path.replace("\\", "/").lstrip("./")
    for candidate in (path, f"weebot/{path}"):
        if candidate in tracked_set:
            return candidate
    hits = [t for t in tracked if t.endswith("/" + path)]
    return hits[0] if len(hits) == 1 else None


def broken_citations() -> list[str]:
    tracked = _tracked()
    tracked_set = set(tracked)
    lengths: dict[str, int] = {}
    problems: list[str] = []
    for card in sorted((ROOT / "map" / "objects").rglob("*.md")):
        if card.name in ("_index.md", "CONTEXT.md"):
            continue
        text = card.read_text(encoding="utf-8")
        if "status: verified" not in text:
            continue
        rel = card.relative_to(ROOT).as_posix()
        for m in _CITE.finditer(text):
            path, first, last = m.group(1), m.group(2), m.group(3)
            resolved = _resolve(path, tracked, tracked_set)
            if resolved is None:
                if "/" in path:  # a bare file name ("config.py") is prose, not a citation
                    problems.append(f"{rel}: {path} is not a tracked file")
                continue
            if first:
                if resolved not in lengths:
                    lengths[resolved] = sum(
                        1 for _ in (ROOT / resolved).open(encoding="utf-8", errors="ignore")
                    )
                line = int(last or first)
                if line > lengths[resolved]:
                    problems.append(
                        f"{rel}: {path}:{line} is past the end ({lengths[resolved]} lines)"
                    )
    return problems


def main() -> int:
    problems = broken_citations()
    for p in problems:
        print(p)
    print(f"{len(problems)} broken citation(s) in verified map cards")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
