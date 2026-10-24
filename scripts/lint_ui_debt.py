#!/usr/bin/env python3
"""Count UI debt in ``weebot-ui/src`` as bidirectional ratchets.

Phase 0.4 of ``tasks/specs/ui_ux_remediation_plan.md``. Each counter has a ceiling in
``tasks/quality/ceilings.toml`` (exact equality both ways, see ``quality_ceilings.py``):

* ``ui_orientation_selectors``   ``data-horizontal:`` / ``data-vertical:`` (base-ui emits
  ``data-orientation``, so these never match)
* ``ui_tiny_text``               ``text-[10px]`` / ``text-[11px]``
* ``ui_viewport_height``         ``100vh`` (use ``dvh``; ``vh`` ignores mobile browser chrome)
* ``ui_main_landmarks``          ``<main`` elements in components and routes (one per page)
* ``ui_click_on_static``         ``onClick`` on ``div``/``span``/``li`` (not keyboard reachable)
* ``ui_layer_violations``        ``components/ui`` importing hooks/providers/lib (except
  ``lib/utils``), or ``lib/`` importing ``react``

Usage:
    python scripts/lint_ui_debt.py          # check every counter against its ceiling
    python scripts/lint_ui_debt.py --list   # print each hit
"""

from __future__ import annotations

import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = _ROOT / "weebot-ui" / "src"

_UI_IMPORT = re.compile(r"""from\s+["']@/(hooks|providers|lib)(/[^"']*)?["']""")
_REACT_IMPORT = re.compile(r"""from\s+["']react(-dom)?(/[^"']*)?["']""")

COUNTERS: dict[str, re.Pattern[str]] = {
    "ui_orientation_selectors": re.compile(r"(?<![\w\[-])(?:group-)?data-(?:horizontal|vertical)\b"),
    "ui_tiny_text": re.compile(r"text-\[1[01]px\]"),
    "ui_viewport_height": re.compile(r"\d\s*vh\b|\bh-screen\b|\bmin-h-screen\b"),
    "ui_main_landmarks": re.compile(r"<main[\s>]"),
    # An element with an explicit role (an ARIA option, say) is interactive by declaration.
    "ui_click_on_static": re.compile(r"<(?:div|span|li)\b(?![^>]*\brole=)[^>]*\bonClick="),
}


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def _code(text: str) -> str:
    """*text* with comments blanked, keeping line numbers (a comment may name `<main>`)."""
    def blank(m: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    return _LINE_COMMENT.sub(blank, _BLOCK_COMMENT.sub(blank, text))


def _files() -> list[pathlib.Path]:
    return [
        p for p in sorted(_SRC.rglob("*"))
        if p.suffix in {".ts", ".tsx", ".css"} and ".test." not in p.name
    ]


def hits(root: pathlib.Path = _SRC) -> dict[str, list[str]]:
    """``counter -> ["path:line", ...]`` for every counter, zero-filled."""
    found: dict[str, list[str]] = {name: [] for name in (*COUNTERS, "ui_layer_violations")}
    for path in _files():
        rel = path.relative_to(root).as_posix()
        text = _code(path.read_text(encoding="utf-8"))
        for name, pattern in COUNTERS.items():
            # <div ... onClick> may span lines; match on the whole text, report the start line.
            for m in pattern.finditer(text):
                found[name].append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
        for lineno, line in enumerate(text.splitlines(), 1):
            if rel.startswith("components/ui/"):
                m = _UI_IMPORT.search(line)
                if m and not (m.group(1) == "lib" and m.group(2) == "/utils"):
                    found["ui_layer_violations"].append(f"{rel}:{lineno}")
            elif rel.startswith("lib/") and _REACT_IMPORT.search(line):
                found["ui_layer_violations"].append(f"{rel}:{lineno}")
    return found


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    found = hits()
    if "--list" in argv:
        for name, where in found.items():
            print(f"{name}: {len(where)}")
            for w in where:
                print(f"  {w}")
        return 0
    status = 0
    for name, where in found.items():
        code, message = check(name, len(where))
        print(message)
        status |= code
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
