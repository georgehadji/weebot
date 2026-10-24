#!/usr/bin/env python3
"""Count the reviewed exemptions in .importlinter, as a bidirectional ratchet.

Phase 3.4 of ``tasks/specs/arch_audit_2026_09_remediation_plan.md``.

Each ``ignore_imports`` entry is an edge a contract would otherwise forbid.
The count had only ever been tracked in prose, and the prose targets moved
the wrong way: ADR-001 recorded 52, ARCHITECTURE.md D3 recorded 35 against a
target of <=25, and the file held 67 -- measured per commit from git, rising
53 -> 67 over six weeks with a peak of 72. A number in a markdown file is not
a gate.

Enforced like the other ratchets: the run fails when the count exceeds the
ceiling in ``tasks/quality/ceilings.toml`` *and* when it falls below it. Lower
the ceiling in the commit that removes an exemption.

Exit code: 0 only when count == ceiling.

Dynamic imports (plan ``arch_audit_2026_10_remediation_plan.md`` item 0.2, LAY-4).
``importlib.import_module("weebot.x")`` hides an edge from import-linter, so
the same boundary can be crossed there with no exemption for a reviewer to
see. This script also:

* counts literal ``import_module("weebot.…")`` / ``__import__("weebot.…")``
  targets and ratchets them as ``dynamic_weebot_imports``;
* checks each one against the ``forbidden`` contracts in ``.importlinter``
  (direct edge, ``ignore_imports`` honoured), and fails when a dynamic import
  crosses a boundary that has neither an exemption nor an entry in
  ``_HIDDEN_VIOLATIONS`` below. That table is the visible, ratcheted home of
  the hidden edges: each row names the owning plan item, and a row is deleted
  when the site is fixed.

Usage:
    python scripts/lint_import_exemptions.py
"""

from __future__ import annotations

import ast
import configparser
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / ".importlinter"


def count_exemptions() -> dict[str, int]:
    """``{contract id: active ignore_imports entries}``. Comments do not count."""
    parser = configparser.ConfigParser()
    parser.optionxform = str  # keep case
    parser.read(_CONFIG, encoding="utf-8")
    counts: dict[str, int] = {}
    for section in parser.sections():
        if not section.startswith("importlinter:contract:"):
            continue
        raw = parser[section].get("ignore_imports", "")
        entries = [
            line.strip()
            for line in raw.splitlines()
            if "->" in line and not line.strip().startswith("#")
        ]
        counts[section.split(":", 2)[-1]] = len(entries)
    return counts


# (importing module, dynamic target) -> what removes the row.
_HIDDEN_VIOLATIONS: dict[tuple[str, str], str] = {
    ("weebot.interfaces.factories", "weebot.infrastructure.mcp.mcp_toolkit_adapter"): "plan 3.7: MCP wiring registered at the edge",
    ("weebot.interfaces.factories", "weebot.infrastructure.adapters.apify"): "plan 3.7: Apify wiring registered at the edge",
    ("weebot.interfaces.factories", "weebot.tools.apify_presets"): "plan 3.7: Apify wiring registered at the edge",
    ("weebot.interfaces.web.main", "weebot.infrastructure.adapters.llm.resilient_adapter"): "breaker state persistence; needs a port method",
    ("weebot.interfaces.web.routers.health", "weebot.infrastructure.browser.session_pool"): "health probe; needs a port method",
    ("weebot.interfaces.web.routers.health", "weebot.infrastructure.cache.llm_cache"): "health probe; needs a port method",
}


def _ceiling_check(actual: int, name: str = "import_exemptions") -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check(name, actual)


def _under(module: str, prefixes: list[str]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def _glob(pattern: str) -> re.Pattern[str]:
    out = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^.]*")
    return re.compile(out + r"\Z")


def _forbidden_contracts() -> list[tuple[str, list[str], list[str], list[re.Pattern[str]]]]:
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(_CONFIG, encoding="utf-8")
    contracts = []
    for section in parser.sections():
        if not section.startswith("importlinter:contract:"):
            continue
        body = parser[section]
        if body.get("type") != "forbidden":
            continue
        sources = body.get("source_modules", "").split()
        banned = body.get("forbidden_modules", "").split()
        ignored = []
        for line in body.get("ignore_imports", "").splitlines():
            line = line.strip()
            if "->" in line and not line.startswith("#"):
                left, right = (part.strip() for part in line.split("->"))
                ignored.append(_glob(f"{left} -> {right}"))
        contracts.append((section.split(":", 2)[-1], sources, banned, ignored))
    return contracts


def dynamic_imports() -> list[tuple[str, int, str]]:
    """``(importing module, line, "weebot.x")`` for each literal dynamic import."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from lint_module_cycles import discover, literal_dynamic_targets

    found = []
    for module, path in discover().items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend((module, line, target) for line, target in literal_dynamic_targets(tree))
    return found


def hidden_violations(sites: list[tuple[str, int, str]]) -> list[tuple[str, int, str, str]]:
    """Dynamic imports that cross a forbidden boundary with no exemption."""
    contracts = _forbidden_contracts()
    bad = []
    for module, line, target in sites:
        for contract, sources, banned, ignored in contracts:
            if not (_under(module, sources) and _under(target, banned)):
                continue
            if any(rx.match(f"{module} -> {target}") for rx in ignored):
                continue
            bad.append((module, line, target, contract))
    return bad


def main(argv: list[str]) -> int:
    counts = count_exemptions()
    for contract, n in sorted(counts.items()):
        print(f"{contract:24s} {n:3d}")
    code, message = _ceiling_check(sum(counts.values()))
    print(f"\n{message}")
    if code:
        print(
            "Remove the violation rather than exempting it, or -- if an exemption\n"
            "was removed -- lower `import_exemptions` in tasks/quality/ceilings.toml.",
            file=sys.stderr,
        )

    sites = dynamic_imports()
    dyn_code, dyn_message = _ceiling_check(len(sites), "dynamic_weebot_imports")
    print(dyn_message, file=sys.stderr if dyn_code else sys.stdout)
    if dyn_code:
        print(
            "A literal import_module('weebot.…') hides an edge from import-linter. Use a\n"
            "static import; if the target is an optional dependency, say so in the commit.",
            file=sys.stderr,
        )
    found = {(m, t): (line, c) for m, line, t, c in hidden_violations(sites)}
    unlisted = sorted(set(found) - set(_HIDDEN_VIOLATIONS))
    stale = sorted(set(_HIDDEN_VIOLATIONS) - set(found))
    for module, target in unlisted:
        line, contract = found[(module, target)]
        print(
            f"{module}:{line} imports {target} dynamically across contract "
            f"{contract!r} with no exemption. Import it statically (the exemption "
            "then shows in .importlinter) or route it through a port.",
            file=sys.stderr,
        )
    for module, target in stale:
        print(
            f"_HIDDEN_VIOLATIONS lists ({module}, {target}) but the site no longer "
            "crosses a boundary. Delete the row.",
            file=sys.stderr,
        )
    return code or dyn_code or int(bool(unlisted or stale))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
