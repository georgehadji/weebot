#!/usr/bin/env python3
"""Generate AGENTS.md, GEMINI.md and QWEN.md from CLAUDE.md.

CLAUDE.md is the only hand-edited entry file. The twins exist because other agent
tools read their own filename. Hand edits to a twin are overwritten.

  python scripts/gen_entry_twins.py          # rewrite the twins
  python scripts/gen_entry_twins.py --check  # exit 1 if any twin differs (gate)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "CLAUDE.md"
TWINS = ["AGENTS.md", "GEMINI.md", "QWEN.md"]
HEADER = (
    "<!-- GENERATED from CLAUDE.md by scripts/gen_entry_twins.py. "
    "Do not edit; edit CLAUDE.md and run `make gen-entry-twins`. -->\n\n"
)


def expected() -> bytes:
    body = SOURCE.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return (HEADER + body).encode("utf-8")


def main() -> int:
    want = expected()
    # Line endings are not drift: git's core.autocrlf rewrites them on checkout.
    stale = [
        n for n in TWINS
        if not (ROOT / n).exists() or (ROOT / n).read_bytes().replace(b"\r\n", b"\n") != want
    ]
    if "--check" in sys.argv:
        for n in stale:
            print(f"{n} differs from CLAUDE.md; run `make gen-entry-twins`")
        return 1 if stale else 0
    for n in stale:
        (ROOT / n).write_bytes(want)
        print(f"wrote {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
