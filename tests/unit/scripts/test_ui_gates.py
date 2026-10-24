"""The UI ratchets (tasks/specs/ui_ux_remediation_plan.md, Phases 0.4 and 6.1)."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_SCRIPTS = pathlib.Path(__file__).resolve().parents[3] / "scripts"


def _load(name: str):
    sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


debt = _load("lint_ui_debt")
contrast = _load("check_ui_contrast")


def _count(tmp_path, name: str, files: dict[str, str]) -> int:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    original = debt._SRC
    debt._SRC = tmp_path
    try:
        return len(debt.hits(tmp_path)[name])
    finally:
        debt._SRC = original


@pytest.mark.parametrize(
    ("counter", "files", "expected"),
    [
        ("ui_orientation_selectors", {"a.tsx": '"data-horizontal:flex-col group-data-vertical/x:h-1"'}, 2),
        ("ui_orientation_selectors", {"a.tsx": '"data-[orientation=horizontal]:flex-col"'}, 0),
        ("ui_tiny_text", {"a.tsx": '"text-[10px] text-[11px] text-xs"'}, 2),
        ("ui_viewport_height", {"a.tsx": '"h-[calc(100vh-4rem)] min-h-screen h-dvh"'}, 2),
        ("ui_main_landmarks", {"a.tsx": "<main className='x'>...</main>"}, 1),
        ("ui_main_landmarks", {"a.tsx": "/* <main> in a comment */\n// <main>\n<mainframe />"}, 0),
        ("ui_click_on_static", {"a.tsx": "<div className='x' onClick={go}>"}, 1),
        ("ui_click_on_static", {"a.tsx": '<li role="option" onClick={go}>'}, 0),
        ("ui_click_on_static", {"a.tsx": "<button onClick={go}>"}, 0),
    ],
)
def test_each_counter_counts_what_it_names(tmp_path, counter, files, expected):
    assert _count(tmp_path, counter, files) == expected


def test_ui_components_may_not_reach_into_hooks_providers_or_lib(tmp_path):
    files = {
        "components/ui/ok.tsx": 'import { cn } from "@/lib/utils"',
        "components/ui/bad1.tsx": 'import { x } from "@/hooks/useThing"',
        "components/ui/bad2.tsx": 'import { y } from "@/lib/api"',
        "components/other/fine.tsx": 'import { x } from "@/hooks/useThing"',
    }
    assert _count(tmp_path, "ui_layer_violations", files) == 2


def test_lib_stays_free_of_react(tmp_path):
    files = {
        "lib/pure.ts": 'import { z } from "@/types/events"',
        "lib/impure.ts": 'import { useState } from "react"',
    }
    assert _count(tmp_path, "ui_layer_violations", files) == 1


def test_the_real_source_is_at_its_ceilings():
    from quality_ceilings import check  # noqa: PLC0415 - path set by _load

    for name, where in debt.hits().items():
        code, message = check(name, len(where))
        assert code == 0, message


def test_contrast_maths_matches_the_wcag_reference_values():
    white, black = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    assert contrast.contrast(white, black) == pytest.approx(21.0)
    assert contrast.contrast(white, white) == pytest.approx(1.0)


def test_a_failing_pair_is_reported_and_a_passing_one_is_not():
    css = """
    :root { --foreground: 0 0% 60%; --background: 0 0% 100%; }
    .dark { --foreground: 0 0% 100%; --background: 0 0% 0%; }
    """
    rows = {(theme, fg): ratio for theme, fg, _bg, ratio in contrast.check(css)}
    assert rows[("light", "foreground")] < contrast.AA_TEXT
    assert rows[("dark", "foreground")] > contrast.AA_TEXT


def test_var_references_and_comments_in_the_stylesheet_are_followed():
    css = """
    :root { --p: 0 0% 0%; --foreground: var(--p); --background: 0 0% 100%; /* a; b */ }
    """
    (row,) = [r for r in contrast.check(css) if r[0] == "light"]
    assert row[3] == pytest.approx(21.0)


def test_every_token_pair_in_the_real_stylesheet_meets_aa():
    failing = [r for r in contrast.check(contrast._CSS.read_text(encoding="utf-8")) if r[3] < contrast.AA_TEXT]
    assert failing == []
