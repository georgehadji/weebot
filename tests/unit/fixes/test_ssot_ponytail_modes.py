"""One set of Ponytail modes (SSOT audit row 25).

Settings, the skill-prompt service, the web router, the CLI command and the
gateway command parser each spelled `{"off", "lite", "full", "ultra"}`.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]

COPIES = (
    "weebot/application/services/ponytail_skill_prompt.py",
    "weebot/interfaces/web/routers/ponytail.py",
    "cli/commands/ponytail.py",
    "weebot/interfaces/gateways/base.py",
)


def test_settings_owns_the_mode_set():
    from weebot.config.settings import PONYTAIL_MODES

    assert PONYTAIL_MODES == frozenset({"off", "lite", "full", "ultra"})


def test_no_other_module_spells_the_set():
    for rel in COPIES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert '"off", "lite", "full", "ultra"' not in text, rel
