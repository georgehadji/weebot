"""One default for the sessions database path (SSOT audit row 10).

`settings.SESSIONS_DB` reads `WEEBOT_SESSIONS_DB`, but a dozen constructors and
CLI options carried their own `"./weebot_sessions.db"` default. With the env var
set, everything built from defaults -- `Container().configure_defaults()` among
them -- kept writing to `./weebot_sessions.db` while the rest moved.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_only_settings_spells_the_default_path():
    hits = []
    for top in ("weebot", "cli"):
        for path in (ROOT / top).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "weebot/config/settings.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(
                    node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
            }
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                    and node.value.endswith("weebot_sessions.db")
                ):
                    hits.append(f"{rel}:{node.lineno}")
    assert hits == []


def test_configure_defaults_follows_the_env_var():
    import inspect

    from weebot.application.di import Container
    from weebot.config import constants

    default = inspect.signature(Container.configure_defaults).parameters["db_path"].default
    assert default == constants.DB_SESSIONS_PATH
