"""The prompt-surface lock fails on a change and passes after a re-lock (H10)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prompt_surface.py"


@pytest.fixture
def surface(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("prompt_surface_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "LOCK", tmp_path / "prompt_surface.lock")
    monkeypatch.setattr(module, "TEXT_DIR", tmp_path / "prompt_surface")
    # The lock compares paths relative to the repository; a temp lock is outside it.
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


SURFACES = {"system_static.full": "be careful\nuse tools\n", "tools.admin": "[]\n"}


def test_an_unchanged_surface_passes_after_locking(surface):
    surface.update(SURFACES)

    assert surface.check(dict(SURFACES)) == []


def test_a_changed_line_fails_and_the_diff_shows_it(surface):
    surface.update(SURFACES)

    problems = surface.check({**SURFACES, "system_static.full": "be careful\nuse tools twice\n"})

    assert len(problems) == 1
    assert "-use tools" in problems[0] and "+use tools twice" in problems[0]


def test_a_surface_added_or_removed_fails(surface):
    surface.update(SURFACES)

    added = surface.check({**SURFACES, "tools.automation": "[]\n"})
    removed = surface.check({"tools.admin": "[]\n"})

    assert added == ["tools.automation: rendered but not locked"]
    assert removed == ["system_static.full: locked but no longer rendered"]


def test_no_lock_file_fails_with_the_command_to_make_one(surface):
    assert "--update" in surface.check(dict(SURFACES))[0]
