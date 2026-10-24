#!/usr/bin/env python3
"""Count import cycles between modules of ``weebot/``, as a bidirectional ratchet.

Phase 0.1 of ``tasks/specs/arch_audit_2026_10_remediation_plan.md`` (LAY-2).

import-linter checks which *layer* may import which. It does not look for a loop
between two modules of the same layer, so a ring of states that import their
successors passes every contract. This walks the AST import graph and runs
Tarjan's strongly-connected-components algorithm; each SCC with more than one
module is one cycle.

What counts as an edge:

* ``import weebot.x`` / ``from weebot.x import y`` anywhere in the file, inside
  a function included (a lazy import is still an edge at run time);
* literal ``importlib.import_module("weebot.x")`` / ``__import__("weebot.x")``
  targets, because those are the edges import-linter cannot see (plan item 0.2);
* NOT imports under ``if TYPE_CHECKING:``, which never execute.

Enforced like the other ratchets: fails above the ceiling in
``tasks/quality/ceilings.toml`` and below it. Lower ``module_cycles`` in the
commit that breaks a cycle.

Usage:
    python scripts/lint_module_cycles.py            # check against the ceiling
    python scripts/lint_module_cycles.py --list     # also print each SCC's members
"""

from __future__ import annotations

import ast
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PKG = "weebot"

_DYNAMIC_CALLS = {"import_module", "__import__"}


def module_name(path: pathlib.Path, root: pathlib.Path = _ROOT) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def discover(root: pathlib.Path = _ROOT) -> dict[str, pathlib.Path]:
    return {
        module_name(p, root): p
        for p in sorted((root / _PKG).rglob("*.py"))
        if "GitNexus-main" not in p.parts
    }


def _type_checking_nodes(tree: ast.AST) -> set[int]:
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
            for child in node.body:
                skipped.update(id(x) for x in ast.walk(child))
    return skipped


def literal_dynamic_targets(tree: ast.AST) -> list[tuple[int, str]]:
    """``(lineno, "weebot.x")`` for every literal ``import_module``/``__import__`` call."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        arg = node.args[0]
        if (
            name in _DYNAMIC_CALLS
            and isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and (arg.value == _PKG or arg.value.startswith(_PKG + "."))
        ):
            found.append((node.lineno, arg.value))
    return found


def edges_of(module: str, path: pathlib.Path, known: set[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    skipped = _type_checking_nodes(tree)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    targets: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Import):
            targets.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join(anchor + ([node.module] if node.module else []))
            elif node.module:
                base = node.module
            else:
                continue
            targets.add(base)
            targets.update(f"{base}.{a.name}" for a in node.names)
    targets.update(t for _, t in literal_dynamic_targets(tree))
    return {t for t in targets if t in known and t != module}


def build_graph(root: pathlib.Path = _ROOT) -> dict[str, list[str]]:
    mods = discover(root)
    known = set(mods)
    return {m: sorted(edges_of(m, p, known)) for m, p in mods.items()}


def strongly_connected(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan, iterative so a deep import chain cannot hit the recursion limit."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for start in graph:
        if start in index:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, i = work.pop()
            if i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            recurse = False
            neighbours = graph[node]
            while i < len(neighbours):
                nxt = neighbours[i]
                i += 1
                if nxt not in index:
                    work.append((node, i))
                    work.append((nxt, 0))
                    recurse = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if recurse:
                continue
            if low[node] == index[node]:
                comp: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                if len(comp) > 1:
                    result.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return sorted(result, key=lambda c: (-len(c), c))


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    cycles = strongly_connected(build_graph())
    for comp in cycles:
        print(f"cycle of {len(comp)}:")
        shown = comp if "--list" in argv else comp[:4]
        for member in shown:
            print(f"    {member}")
        if len(shown) < len(comp):
            print(f"    ... {len(comp) - len(shown)} more (--list)")
    code, message = check("module_cycles", len(cycles))
    print(f"\n{message}")
    if code:
        print(
            "Break the cycle (a state returns a Transition, a composition root stops\n"
            "importing its caller) or, if one was broken, lower `module_cycles` in\n"
            "tasks/quality/ceilings.toml.",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
