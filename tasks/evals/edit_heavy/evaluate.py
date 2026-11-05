"""Score an edit_heavy sample by reading the files the agent left on disk.

``expected_answer`` is JSON: ``{"dir": ..., "files": {name: {"has": [...], "lacks": [...],
"count": {text: n}}}}``. Returns 1.0 when every file matches and still parses as Python, else 0.0.
"""

import ast
import json
from pathlib import Path


def _file_ok(path: Path, rule: dict) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        ast.parse(text)
    except SyntaxError:
        return False
    return (
        all(s in text for s in rule.get("has", []))
        and not any(s in text for s in rule.get("lacks", []))
        and all(text.count(s) == n for s, n in rule.get("count", {}).items())
    )


def evaluate(session, expected_answer: str) -> float:
    if not expected_answer:
        return 0.0
    spec = json.loads(expected_answer)
    root = Path(spec["dir"])
    return 1.0 if all(_file_ok(root / name, rule) for name, rule in spec["files"].items()) else 0.0
