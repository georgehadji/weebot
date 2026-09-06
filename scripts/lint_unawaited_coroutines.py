#!/usr/bin/env python3
"""Gate: coroutine functions called as a bare statement, never awaited.

The D59 shape: `async def f(): ...` called as `f(...)` on its own line. Python
builds a coroutine object, runs nothing, raises nothing. The only signal is a
RuntimeWarning at GC, which nothing reads.

Resolution is deliberately narrow, because a bare-name heuristic is worthless
here: matching `write_text` by name alone reports every `pathlib.Path.write_text`
in the tree against an async port method that shares the name. Only two forms
are resolvable without imports, and both are exactly the D59 shape:

  * a module-level `async def` called by bare name in the same module;
  * an `async def` method called as `self.method(...)` in the same class.

Not a ratchet: the count is zero and must stay zero. There is no legitimate
reason to build a coroutine and drop it, so there is no debt to grandfather.

Proven to fail on the defect it exists for -- run against
`git show HEAD~:weebot/core/behavior_tracker.py` it reports all nine sites. A
gate nobody has watched fail is not a gate.
"""
import ast
import sys
from pathlib import Path

ROOTS = [Path("weebot"), Path("cli")]
findings, scanned = [], 0

def bare_calls(body_owner, names, label, path, kind):
    """Report bare-statement calls to *names* inside *body_owner*."""
    for node in ast.walk(body_owner):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        if kind == "module" and isinstance(fn, ast.Name) and fn.id in names:
            findings.append((f"{path}:{node.lineno}", f"{fn.id}(...)", label))
        elif (kind == "self" and isinstance(fn, ast.Attribute)
              and isinstance(fn.value, ast.Name) and fn.value.id == "self"
              and fn.attr in names):
            findings.append((f"{path}:{node.lineno}", f"self.{fn.attr}(...)", label))

for root in ROOTS:
    for f in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        scanned += 1
        # Module-level async defs, called by bare name anywhere in this module.
        mod_async = {n.name for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
        # A name rebound by a sync def at module level is ambiguous; drop it.
        mod_async -= {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        if mod_async:
            bare_calls(tree, mod_async, f"module-level async def in {f.name}", f, "module")
        # Async methods, called as self.m() inside the same class.
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            m_async = {n.name for n in cls.body if isinstance(n, ast.AsyncFunctionDef)}
            m_async -= {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
            if m_async:
                bare_calls(cls, m_async, f"async method of {cls.name}", f, "self")

if findings:
    print(f"{len(findings)} coroutine call(s) built and dropped:\n")
    for site, call, why in findings:
        print(f"  {site}: {call}  -- {why}")
else:
    print("No un-awaited coroutine calls found (same-module / same-class resolution).")
print(f"\nscanned {scanned} files")
sys.exit(1 if findings else 0)
