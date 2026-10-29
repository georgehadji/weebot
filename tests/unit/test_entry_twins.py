"""The entry-twin gate compares content, not line endings.

With git's core.autocrlf on (the default on Windows), a checkout rewrites the generated
twins with CRLF endings. The gate compared raw bytes, so every branch switch made it fail
although no twin had drifted from CLAUDE.md.
"""

import importlib.util
import sys
from pathlib import Path


def _script(root: Path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "gen_entry_twins", Path("scripts/gen_entry_twins.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "SOURCE", root / "CLAUDE.md")
    return module


def _check(module, monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["gen_entry_twins.py", "--check"])
    return module.main()


def test_twins_checked_out_with_crlf_are_not_drift(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_bytes(b"# CLAUDE.md\r\n\r\nRules.\r\n")
    module = _script(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["gen_entry_twins.py"])
    module.main()
    for name in module.TWINS:
        twin = tmp_path / name
        twin.write_bytes(twin.read_bytes().replace(b"\n", b"\r\n"))
    assert _check(module, monkeypatch) == 0


def test_a_twin_with_other_content_is_drift(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_bytes(b"# CLAUDE.md\n\nRules.\n")
    module = _script(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["gen_entry_twins.py"])
    module.main()
    (tmp_path / "AGENTS.md").write_bytes(b"hand edit\n")
    assert _check(module, monkeypatch) == 1
