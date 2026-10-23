"""Provider base URLs live in `weebot/config/api_endpoints.py` (audit row 28).

That module says "all modules import base URLs from here", and about ten call
sites still spelled the OpenRouter, DeepSeek or xAI base inline.
"""

from __future__ import annotations

import ast
import pathlib

from weebot.config import api_endpoints

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASES = tuple(
    value
    for name, value in vars(api_endpoints).items()
    if name.endswith("_API_BASE") and isinstance(value, str)
)


def test_no_module_spells_a_provider_base_url():
    hits = []
    for top in ("weebot", "cli"):
        for path in (ROOT / top).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "weebot/config/api_endpoints.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith(BASES)
                ):
                    hits.append(f"{rel}:{node.lineno} {node.value}")
    assert hits == []
