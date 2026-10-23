"""Every `[project.scripts]` entry names a callable that exists.

`weebot = "cli.main:main"`, but `cli/main.py` defines no `main` (its entry is
`_wrap_main`), so an installed `weebot` command failed on import (F44).
"""

from __future__ import annotations

import importlib
import pathlib
import tomllib


def test_each_console_script_resolves():
    root = pathlib.Path(__file__).resolve().parents[3]
    scripts = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "scripts"
    ]
    for name, target in scripts.items():
        module, _, attr = target.partition(":")
        assert callable(getattr(importlib.import_module(module), attr, None)), (name, target)
