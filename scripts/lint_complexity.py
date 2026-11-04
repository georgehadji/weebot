#!/usr/bin/env python3
"""Count functions that are too branchy or too deeply nested in ``weebot/``, as ratchets.

Plan Q1 (``tasks/specs/hermes_v022_parity_implementation_plan.md``), matrix row 42.
Hermes holds each unit to a complexity rule; Weebot holds the *count* of units over
the rule, with the exact-equality mechanism of ``tasks/quality/ceilings.toml``.

Two measures, both per function (a nested function is its own unit and does not
count toward its parent):

* **Cyclomatic complexity**: 1, plus one for each ``if``, conditional expression,
  loop, ``except`` handler, ``match`` case, comprehension clause and comprehension
  ``if``, and one for each extra operand of ``and`` / ``or``. Over 20 is counted in
  ``functions_over_cc_20``.
* **Nesting depth**: the deepest chain of ``if`` / ``for`` / ``while`` / ``try`` /
  ``with`` / ``match`` blocks inside the function (the first block is depth 1).
  Over 6 is counted in ``functions_over_nesting_6``.

Usage:
    python scripts/lint_complexity.py          # check against both ceilings
    python scripts/lint_complexity.py --list   # print each offender
"""

from __future__ import annotations

import ast
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
CC_LIMIT = 20
NESTING_LIMIT = 6

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPES = (*_FUNCTIONS, ast.Lambda, ast.ClassDef)
_BLOCKS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)
_BRANCHES = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.match_case)
_TRY_STAR = getattr(ast, "TryStar", None)


def _own_nodes(function: ast.AST):
    """Every node of the function except the bodies of nested functions and classes."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def cyclomatic(function: ast.AST) -> int:
    total = 1
    for node in _own_nodes(function):
        if isinstance(node, _BRANCHES):
            total += 1
        elif isinstance(node, ast.BoolOp):
            total += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            total += 1 + len(node.ifs)
    return total


def nesting(function: ast.AST) -> int:
    blocks = (*_BLOCKS, *((_TRY_STAR,) if _TRY_STAR else ()))

    def depth(node: ast.AST, level: int) -> int:
        """Deepest block level among the node's contents; `level` is theirs."""
        deepest = level
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPES):
                continue
            # An `elif` is an `If` alone in the `orelse` of another: same level, not deeper.
            is_elif = (
                isinstance(node, ast.If) and node.orelse == [child] and isinstance(child, ast.If)
            )
            inner = level + 1 if isinstance(child, blocks) and not is_elif else level
            deepest = max(deepest, depth(child, inner))
        return deepest

    return depth(function, 0)


def measure(root: pathlib.Path = _ROOT) -> list[tuple[str, int, str, int, int]]:
    """``(relative path, line, qualified name, complexity, nesting)`` for every function."""
    found = []
    for path in sorted((root / "weebot").rglob("*.py")):
        if "GitNexus-main" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()

        def visit(node: ast.AST, prefix: str, rel: str = rel) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, _FUNCTIONS):
                    name = f"{prefix}{child.name}"
                    found.append((rel, child.lineno, name, cyclomatic(child), nesting(child)))
                    visit(child, name + ".", rel)
                elif isinstance(child, ast.ClassDef):
                    visit(child, f"{prefix}{child.name}.", rel)
                else:
                    visit(child, prefix, rel)

        visit(tree, "")
    return found


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    units = measure()
    too_branchy = sorted((u for u in units if u[3] > CC_LIMIT), key=lambda u: -u[3])
    too_deep = sorted((u for u in units if u[4] > NESTING_LIMIT), key=lambda u: -u[4])
    if "--list" in argv:
        print(f"-- complexity over {CC_LIMIT}")
        for rel, line, name, cc, _ in too_branchy:
            print(f"{cc:5d}  {rel}:{line}  {name}")
        print(f"-- nesting over {NESTING_LIMIT}")
        for rel, line, name, _, depth in too_deep:
            print(f"{depth:5d}  {rel}:{line}  {name}")
    status = 0
    for key, count in (
        ("functions_over_cc_20", len(too_branchy)),
        ("functions_over_nesting_6", len(too_deep)),
    ):
        code, message = check(key, count)
        print(message, file=sys.stderr if code else sys.stdout)
        status |= code
    if status:
        print(
            "Split the function rather than raising the ceiling; if one was split, lower\n"
            "the ceiling in tasks/quality/ceilings.toml. `--list` shows each offender.",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
