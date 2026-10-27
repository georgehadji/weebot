"""A04: the Output carve-out judged a path as text, so a junction inside Output led out of it."""

from __future__ import annotations

import subprocess
import sys

import pytest

from weebot.core.approval_policy import ExecApprovalPolicy

needs_windows = pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")


def _asks(command: str) -> bool:
    return ExecApprovalPolicy().evaluate(command).requires_confirmation


def test_plain_output_path_is_still_auto_approved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Output" / "job").mkdir(parents=True)
    assert not _asks(r"Remove-Item Output\job\x.txt -Force")


@pytest.mark.parametrize("kind", ["Junction", "SymbolicLink", "HardLink"])
def test_creating_a_link_inside_output_asks(kind, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Output").mkdir()
    assert _asks(rf"New-Item -ItemType {kind} -Path Output\j -Value C:\Windows")


@needs_windows
def test_a_path_through_an_existing_junction_asks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (tmp_path / "Output").mkdir()
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(tmp_path / "Output" / "j"), str(outside)],
        capture_output=True,
    )
    assert made.returncode == 0, made.stderr
    assert _asks(r"Remove-Item Output\j\x -Recurse -Force")
