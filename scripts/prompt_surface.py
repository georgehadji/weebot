"""Lock the executor's prompt surface, so a prompt or tool-schema change shows in review (H10).

What the model is sent before the conversation starts (the system prompt's stable part for
each context scope, and the tool definitions for each role) decides what the provider's
prompt cache can reuse, and what the agent is told to do. A change to either is a change
of behaviour that no test of ordinary code would notice.

This renders both from fixed inputs, compares them with `tasks/quality/prompt_surface.lock`
and the text under `tasks/quality/prompt_surface/`, and fails with a unified diff when they
differ. It is the same kind of reviewed gate as `tasks/quality/ceilings.toml`: the author
who meant to change the surface runs `--update` and the new text goes in the diff.

Usage:
    python scripts/prompt_surface.py            # check (make lint-prompt-surface)
    python scripts/prompt_surface.py --update   # re-lock after an intended change
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOCK = ROOT / "tasks" / "quality" / "prompt_surface.lock"
TEXT_DIR = ROOT / "tasks" / "quality" / "prompt_surface"
SCOPES = ("full", "minimal", "skill", "creative")
ROLES = ("admin", "automation")


def render() -> dict[str, str]:
    """Each surface by name: the system text per scope, the canonical tools per role."""
    from weebot.application.agents.executor._prompt_builder import build_system_blocks
    from weebot.application.agents.executor._system_prompt import load_executor_system_prompt
    from weebot.application.models.prompt_layout import canonical_tools
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    surfaces: dict[str, str] = {}
    base = load_executor_system_prompt()
    for scope in SCOPES:
        static, _ = asyncio.run(build_system_blocks(base_prompt=base, context_scope=scope))
        surfaces[f"system_static.{scope}"] = static
    from weebot.infrastructure.persistence.session_search_sqlite import SqliteSessionSearch

    # A tool with collaborators is left out of an unwired registry; wire the ones the lock
    # must see. The search port opens no database until it is used.
    wiring = {"collaborators": {"search_history": {"search": SqliteSessionSearch.at(":memory:")}}}
    registry = RoleBasedToolRegistry(wiring=lambda: wiring)
    for role in ROLES:
        tools = canonical_tools(registry.create_tool_collection(role).to_params())
        surfaces[f"tools.{role}"] = json.dumps(tools, indent=1, sort_keys=True) + "\n"
    return surfaces


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _path(name: str) -> Path:
    return TEXT_DIR / f"{name}.txt"


def update(surfaces: dict[str, str]) -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in TEXT_DIR.glob("*.txt"):
        stale.unlink()
    for name, text in surfaces.items():
        _path(name).write_text(text, encoding="utf-8", newline="\n")
    LOCK.write_text(
        json.dumps({n: _sha(t) for n, t in sorted(surfaces.items())}, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def check(surfaces: dict[str, str]) -> list[str]:
    """One unified diff (or a note) per surface that differs from the lock."""
    if not LOCK.exists():
        return [f"{LOCK.relative_to(ROOT)} is missing; run with --update"]
    locked = json.loads(LOCK.read_text(encoding="utf-8"))
    problems: list[str] = []
    for name in sorted(set(locked) | set(surfaces)):
        if name not in surfaces:
            problems.append(f"{name}: locked but no longer rendered")
        elif name not in locked:
            problems.append(f"{name}: rendered but not locked")
        elif _sha(surfaces[name]) != locked[name]:
            old = _path(name).read_text(encoding="utf-8") if _path(name).exists() else ""
            diff = difflib.unified_diff(
                old.splitlines(),
                surfaces[name].splitlines(),
                f"locked/{name}",
                f"current/{name}",
                lineterm="",
            )
            problems.append("\n".join(diff) or f"{name}: differs from the lock")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="re-lock the current surface")
    args = parser.parse_args(argv)
    surfaces = render()
    if args.update:
        update(surfaces)
        print(f"locked {len(surfaces)} prompt surfaces in {LOCK.relative_to(ROOT)}")
        return 0
    problems = check(surfaces)
    if problems:
        print("The prompt surface changed. If that was intended, run:")
        print("    python scripts/prompt_surface.py --update")
        print("and commit the new lock and text.\n")
        print("\n\n".join(problems))
        return 1
    print(f"prompt surface unchanged ({len(surfaces)} surfaces)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
