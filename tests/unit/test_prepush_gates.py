"""``scripts/prepush_gates.py`` runs the gates of ``make check`` without make.

``make`` is not installed on the Windows machine, so the gate list could not be run
before a push and two ratchets failed only in CI (master plan, track B1). The script
reads the Makefile, so the two cannot drift apart.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SAMPLE = """\
check: test lint-a
\t@echo "=== All checks passed ==="

test:
\tpytest tests/ -q

lint-a:
\t@echo "=== a ==="
\t@count=$$(grep -c x \\
\t    file.txt); \\
\t  python scripts/q.py --actual "$$count"
"""


def _script():
    spec = importlib.util.spec_from_file_location(
        "prepush_gates", Path("scripts/prepush_gates.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_gates_are_the_check_prerequisites_with_their_commands():
    gates = _script().gates(_SAMPLE)
    assert [name for name, _ in gates] == ["test", "lint-a"]
    assert gates[0][1] == ["pytest tests/ -q"]
    # echo lines are dropped, make's $$ becomes $, and continued lines are one command
    assert gates[1][1] == [
        'count=$(grep -c x file.txt); python scripts/q.py --actual "$count"'
    ]


def test_the_real_makefile_yields_the_full_gate_list():
    names = [name for name, _ in _script().gates(Path("Makefile").read_text(encoding="utf-8"))]
    assert names[0] == "test"
    assert {"check-arch", "lint-imports", "lint-ruff", "lint-env-access", "lint-map-drift"} <= set(
        names
    )
