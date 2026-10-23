"""One exception family (SSOT audit row 18).

`weebot/core/error_system_base.py` (with `errors.py`, `error_system_handler.py`
and `error_system_user_messages.py`, about 1,000 lines) defined a second
`WeebotError` / `ErrorCode` / `ErrorSeverity` family that disagreed with
`weebot/domain/exceptions.py` ("E3000" against "security_violation", six
severities against three) and that no module outside itself imported.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_only_the_domain_defines_the_error_family():
    owners = {}
    for path in (ROOT / "weebot").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and node.name in ("WeebotError", "ErrorSeverity"):
                owners.setdefault(node.name, []).append(path.relative_to(ROOT).as_posix())
    assert owners == {
        "WeebotError": ["weebot/domain/exceptions.py"],
        "ErrorSeverity": ["weebot/domain/exceptions.py"],
    }
