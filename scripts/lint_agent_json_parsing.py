#!/usr/bin/env python3
"""Ratchet for bare `json.loads` under `weebot/application/agents/`.

CLAUDE.md design rule 2:

    Agents MUST return structured JSON validated via Pydantic models in
    `weebot/models/structured_output.py`

The rule is real — that is a decision, not an inference — and the agents were
migrated to match it. This gate exists so the drift does not simply grow back,
because the divergence had reached ten modules before anyone measured it.

What a bare `json.loads` on a model response costs, measured on
`GoalAgent.decompose` before its migration. Three of five malformed responses
ESCAPED the `except json.JSONDecodeError` written to absorb them:

    "priority": "high"        -> ValueError from int()
    "goals": "oops"           -> AttributeError from .get()
    "max_concurrency": "many" -> ValueError from int()
    "tools": "web_search"     -> accepted, one goal built from characters
    prose instead of JSON     -> fallback (the only case that worked)

`.get(key, default)` substitutes the default only when a key is ABSENT, never
when it is present and wrong. Pydantic validation is what closes that.

NOT every call here is a defect. Tool-call arguments (`_tool_executor`,
`_error_handler`) are a different payload with their own repair path, and
`dreamer`'s remaining call feeds `IdeaProposalList` and IS validated. A count
cannot tell those apart, which is why this is a ceiling rather than a ban: the
seventeen that exist are an inventory to triage, and no new one may join them.

Enforced as a **bidirectional** ratchet. See tasks/quality/ceilings.toml.

Exit code: 0 only when count == ceiling.

Usage:
    python scripts/lint_agent_json_parsing.py
"""
from __future__ import annotations

import ast
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TARGET = _ROOT / "weebot" / "application" / "agents"


def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("agent_json_parsing", actual)


def _sites() -> list[str]:
    found: list[str] = []
    for path in sorted(_TARGET.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("loads", "load")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"
            ):
                found.append(f"{path.relative_to(_ROOT).as_posix()}:{node.lineno}")
    return found


def main() -> int:
    print("=== bare json parsing under application/agents/ (ratcheted) ===")
    sites = _sites()
    for site in sites[-3:]:
        print(f"  {site}")
    if len(sites) > 3:
        print(f"  ... and {len(sites) - 3} more")

    status, message = _ceiling_check(len(sites))
    print(f"\n{message}")
    if status != 0:
        print(
            "CLAUDE.md rule 2: validate model output with a Pydantic model in "
            "weebot/models/structured_output.py — see `parse_structured`."
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
