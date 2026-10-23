"""The ICM system map stays true to the code (ICM A3).

`map/objects/_index.md` is generated from the cards, and every citation in a
verified card resolves to a tracked file and an existing line. A verified card
that is silently wrong costs more than a missing one.
"""

from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_object_index_is_the_generated_one():
    gen = _load("gen_map_index")
    current = (ROOT / "map" / "objects" / "_index.md").read_text(encoding="utf-8")
    assert current.replace("\r\n", "\n") == gen.render(), "run python scripts/gen_map_index.py"


def test_verified_cards_cite_real_files_and_lines():
    assert _load("check_map_citations").broken_citations() == []


def test_a_shifted_citation_is_found_at_its_new_line_and_a_changed_one_is_not():
    relocate = _load("check_map_citations")._relocate
    new = ["import x", "", "def f():", "    return 1", "def g():", "    return 1"]
    assert relocate(["def f():", "    return 1"], new, 1) == 3
    assert relocate(["    return 1"], new, 7) == 6  # nearest of two matches
    assert relocate(["def h():"], new, 3) is None


def test_the_tasks_index_is_the_generated_one():
    gen = _load("gen_tasks_index")
    current = (ROOT / "tasks" / "_index.md").read_text(encoding="utf-8")
    assert current.replace("\r\n", "\n") == gen.render(), "run python scripts/gen_tasks_index.py"
