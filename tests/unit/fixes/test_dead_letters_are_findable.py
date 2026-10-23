"""Dead-lettered sessions land in one place and `doctor` reports them.

The directory was `./.weebot/dead_letter`, relative to whatever folder the
process started in, and nothing read it back: a session that failed to save
was written somewhere nobody looked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import weebot.config.constants as consts
from weebot.infrastructure.persistence import session_persistence_adapter as spa


def test_the_default_dir_is_under_the_home_directory(tmp_path, monkeypatch):
    assert consts.DEAD_LETTER_DIR == Path.home() / ".weebot" / "dead_letter"
    monkeypatch.setattr(consts, "DEAD_LETTER_DIR", tmp_path / "dl")
    assert spa.SessionPersistenceAdapter(repo=MagicMock())._dead_letter_dir == tmp_path / "dl"


def test_doctor_reports_pending_dead_letters(tmp_path, monkeypatch):
    from weebot.interfaces.cli.support import run_doctor

    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "s1_20261023T000000.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(consts, "DEAD_LETTER_DIR", dl)
    check = next(c for c in run_doctor(tmp_path).checks if c.name == "dead_letters")
    assert check.status == "warn" and "1" in check.details
