#!/usr/bin/env python3
"""Every DI binding must be resolved by something, or be named as an orphan.

Phase 0.2 of ``tasks/specs/arch_audit_2026_09_remediation_plan.md``.

The repository already has two instruments that read the import graph:
import-linter and the AST fitness suite. Both answer *may this module
reference that one*, and both answer **yes** for a collaborator that is
imported, registered in the container, constructed at startup, and then
never passed to the object that needs it. That gap is not hypothetical --
three separate controls were sitting in it when this script was written:

* ``llm_pool`` -- the global LLM concurrency bound. Registered at
  ``di/__init__.py:263``; ``ExecutorAgent`` builds its ``CascadeExecutor``
  without an ``llm_pool=`` argument, so the bounded branch of the guard in
  ``_cascade.py`` has never executed.
* ``trust_report_service`` -- registered; the config field is never
  assigned, so the block guarded on it in ``states/completed.py`` is
  unreachable.
* ``event_pipeline`` -- the WP-4 middleware chain. Built at startup,
  registered, and discarded.

An audit document in this repository certifies the first of those as wired
and verified. From the outside a dependency that is registered but never
resolved is indistinguishable from one that works, which is exactly why it
takes a machine to tell them apart.

**What counts as resolution.** A call to one of ``RESOLVERS`` whose first
argument is the key. Those three names are not a guess -- they are every
function in ``weebot/`` and ``cli/`` that takes a registered key as its
first argument, minus ``register`` itself. A new accessor wrapper is
therefore a deliberate edit here rather than a silent hole: until its name
is added, keys reached only through it report as orphans and this fails.

Enforced as a **bidirectional** ratchet, the same contract as the other
five: the run fails when the count exceeds the ceiling in
``tasks/quality/ceilings.toml`` *and* when it falls below it. Lower the
ceiling in the same commit that wires a binding.

Exit code: 0 only when count == ceiling.

Usage:
    python scripts/lint_di_wiring.py
"""

from __future__ import annotations

import ast
import pathlib
import sys
from pathlib import Path

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Where bindings are declared. A `register` call anywhere else is not a
# container binding and is not counted.
DI_PACKAGE = "weebot/application/di"

# Where resolutions may live: the whole runtime surface. Tests are excluded
# deliberately -- a binding resolved only by a test is not wired into the
# product, and counting it would let a test keep a dead feature looking alive.
SEARCH_ROOTS = ("weebot", "cli")

SKIP_PARTS = {".venv", "Output", "node_modules", "__pycache__", "GitNexus-main", "tests"}

REGISTRARS = {"register", "register_instance"}

# See the module docstring: measured, not assumed.
RESOLVERS = {"get", "_maybe_get_str", "_cached"}


def _key(node: ast.expr) -> str | None:
    """The binding key a call's first argument names, if it names one.

    Keys are a mix of string literals (``register("llm_pool", ...)``) and
    types (``register(StateRepositoryPort, ...)``); both forms appear in the
    same method, so both are read here.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _called_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        base = _ROOT / root
        if not base.is_dir():
            continue
        files.extend(p for p in sorted(base.rglob("*.py")) if not SKIP_PARTS & set(p.parts))
    return files


def census() -> tuple[dict[str, str], set[str]]:
    """Return ``({key: "file:line" of its registration}, {resolved keys})``."""
    registered: dict[str, str] = {}
    resolved: set[str] = set()

    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            print(f"{path}: could not parse ({exc})", file=sys.stderr)
            continue
        rel = path.relative_to(_ROOT).as_posix()
        in_di = rel.startswith(DI_PACKAGE)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            key = _key(node.args[0])
            if key is None:
                continue
            name = _called_name(node)
            if name in REGISTRARS:
                if in_di:
                    registered.setdefault(key, f"{rel}:{node.lineno}")
            elif name in RESOLVERS:
                resolved.add(key)

    return registered, resolved


def find_orphans() -> list[tuple[str, str]]:
    """Registered keys that nothing resolves, as ``(key, where)`` pairs."""
    registered, resolved = census()
    return sorted((k, w) for k, w in registered.items() if k not in resolved)


def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("unresolved_di_keys", actual)


def main(argv: list[str]) -> int:
    orphans = find_orphans()
    for key, where in orphans:
        print(f"{where}: DI key {key!r} is registered but never resolved")
    code, message = _ceiling_check(len(orphans))
    print(f"\n{message}")
    if code:
        print(
            "Resolve the binding, or delete it. A binding nobody resolves is a\n"
            "feature nobody noticed was missing -- see phase 2.3 of\n"
            "tasks/specs/arch_audit_2026_09_remediation_plan.md.",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
