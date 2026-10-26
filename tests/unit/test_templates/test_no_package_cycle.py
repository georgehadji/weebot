"""weebot.templates submodules must not import the package back (plan 3.8)."""

from __future__ import annotations

import importlib.util
import pathlib

_SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "lint_module_cycles.py"


def _load():
    spec = importlib.util.spec_from_file_location("lint_module_cycles", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_templates_package_is_not_in_an_import_cycle():
    mod = _load()
    cycles = mod.strongly_connected(mod.build_graph())
    in_templates = [c for c in cycles if any(m.startswith("weebot.templates") for m in c)]
    assert not in_templates, f"weebot.templates import cycle: {in_templates}"
