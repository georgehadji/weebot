"""A19, A31, A32: wiring that pointed at things that are not there."""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import tomllib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_a19_every_module_the_diagnostic_imports_exists():
    tree = ast.parse((ROOT / "run.py").read_text(encoding="utf-8"))
    names = [
        elt.elts[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "modules" for t in node.targets)
        for elt in node.value.elts
    ]
    assert names, "run.py no longer has a `modules` list"
    missing = [n for n in names if importlib.util.find_spec(n) is None]
    assert not missing, f"run.py --diagnostic names modules that do not exist: {missing}"


def test_a31_wheel_includes_the_top_level_packages_the_cli_imports():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = cfg["tool"]["setuptools"]["packages"]["find"]["include"]
    for pkg in ("research_modules", "integrations"):
        assert any(p.startswith(pkg) for p in include), f"{pkg} is missing from packages.find"


def test_a32_the_ui_container_proxy_targets_the_api_prefix():
    env = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))[
        "services"
    ]["weebot-ui"]["environment"]
    pairs = dict(e.split("=", 1) for e in env)
    # route.ts reads BACKEND_URL at runtime; NEXT_PUBLIC_* is fixed at build time.
    assert pairs.get("BACKEND_URL", "").rstrip("/").endswith("/api")
