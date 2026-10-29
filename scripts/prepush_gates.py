"""Run the gates of ``make check`` without make, stopping at the first failure.

``make`` is not installed on the Windows development machine, so the gate list was
not run before pushes and ratchets failed only in CI. This reads the ``check``
prerequisites and their recipes from the Makefile, so the two cannot drift, and runs
each command in bash with the virtualenv's scripts directory first on PATH.

Usage:
    python scripts/prepush_gates.py              # every gate
    python scripts/prepush_gates.py --skip test  # all but the (8-minute) test run
    python scripts/prepush_gates.py --list       # print the gates and their commands
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Scripts CI runs that cannot run here; every other workflow script must be a gate
# (tests/unit/test_prepush_gates.py checks it).
CI_ONLY = {
    "scripts/check_branch_protection.py": "reads the live ruleset through the GitHub API",
}

_TARGET = re.compile(r"^([\w.-]+):(?!=)\s*(.*)$")


def _recipes(makefile: str) -> dict[str, tuple[list[str], list[str]]]:
    """Each target's prerequisites and recipe commands, continuations joined."""
    targets: dict[str, tuple[list[str], list[str]]] = {}
    current: list[str] | None = None
    pending = ""
    for line in makefile.splitlines():
        if line.startswith("\t") and current is not None:
            text = line.strip()
            if pending:
                text = f"{pending} {text}"
            if text.endswith("\\"):
                pending = text[:-1].rstrip()
                continue
            pending = ""
            if text:
                current.append(text)
            continue
        match = _TARGET.match(line)
        if match:
            current = []
            targets[match.group(1)] = (match.group(2).split(), current)
        elif line.strip() and not line.startswith("#"):
            current = None
    return targets


def _command(text: str) -> str | None:
    """A recipe line as bash runs it: no @/- prefix, $$ as $, echo lines dropped."""
    text = text.lstrip("@-").strip().replace("$$", "$")
    if not text or text.startswith("echo ") or text == "echo":
        return None
    return text


def gates(makefile: str) -> list[tuple[str, list[str]]]:
    """The ``check`` prerequisites in order, each with the commands it runs."""
    targets = _recipes(makefile)
    prerequisites, _ = targets["check"]
    return [
        (name, [cmd for line in targets[name][1] if (cmd := _command(line)) is not None])
        for name in prerequisites
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip", action="append", default=[], help="gate to leave out")
    parser.add_argument("--list", action="store_true", help="print the gates and exit")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    selected = [
        (name, cmds)
        for name, cmds in gates((root / "Makefile").read_text(encoding="utf-8"))
        if name not in args.skip
    ]
    if args.list:
        for name, cmds in selected:
            print(name)
            for cmd in cmds:
                print(f"    {cmd}")
        return 0

    bash = shutil.which("bash")
    if bash is None:
        print("bash not found; install Git for Windows or run under WSL.", file=sys.stderr)
        return 2
    env = {**os.environ}
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    for name, cmds in selected:
        print(f"=== {name} ===", flush=True)
        for cmd in cmds:
            if subprocess.run([bash, "-c", cmd], cwd=root, env=env).returncode != 0:
                print(f"FAILED: {name}: {cmd}", file=sys.stderr)
                return 1
    print("=== All gates passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
