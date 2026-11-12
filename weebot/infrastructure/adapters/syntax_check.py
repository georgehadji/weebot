"""In-process syntax checks for the file types an edit tool meets most (H6).

Covers ``.py`` (``ast``), ``.json`` and ``.ipynb`` (``json``), ``.toml`` (``tomllib``) and
``.yaml`` / ``.yml`` (PyYAML, when installed). A language server for the rest is H20.
"""

from __future__ import annotations

import ast
import json
import tomllib
from collections.abc import Callable
from pathlib import PurePath

from weebot.application.ports.syntax_check_port import SyntaxCheckPort


def _python(text: str) -> str | None:
    try:
        ast.parse(text)
    except SyntaxError as exc:
        return f"Python syntax error at line {exc.lineno}: {exc.msg}"
    return None


def _json(text: str) -> str | None:
    try:
        json.loads(text)
    except ValueError as exc:
        return f"JSON error: {exc}"
    return None


def _toml(text: str) -> str | None:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return f"TOML error: {exc}"
    return None


def _yaml(text: str) -> str | None:
    try:
        import yaml
    except ImportError:
        return None
    try:
        list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        return f"YAML error: {str(exc).splitlines()[0]}"
    return None


_CHECKS: dict[str, Callable[[str], str | None]] = {
    ".py": _python,
    ".json": _json,
    ".ipynb": _json,
    ".toml": _toml,
    ".yaml": _yaml,
    ".yml": _yaml,
}


class InProcessSyntaxCheck(SyntaxCheckPort):
    def check(self, path: str, text: str) -> list[str]:
        check = _CHECKS.get(PurePath(path).suffix.lower())
        problem = check(text) if check else None
        return [problem] if problem else []
