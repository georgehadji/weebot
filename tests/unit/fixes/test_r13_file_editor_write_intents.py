"""R13 (audit 2026-10-29): file_editor's whole-file writes follow the create rules.

``write_large`` was validated as an edit, so it could create ``Output/x.ps1`` (scripts are
"read/edit allowed, no create") or overwrite an existing script wholesale. ``str_replace``
with an empty ``old_str`` prepended the new text (``"" in content`` is always true) and
reported "Replaced".
"""

from __future__ import annotations

import pytest

from weebot.infrastructure.security.security_validators import PathValidator
from weebot.tools import file_editor as fe


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setattr(fe, "WORKSPACE_ROOT", str(tmp_path))
    tool = fe.StrReplaceEditorTool()
    tool._workspace = tmp_path.resolve()
    tool._path_validator = PathValidator(workspace_root=tmp_path.resolve())
    return tool


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["x.ps1", "x.bat", "x.cmd", "x.sh"])
async def test_write_large_cannot_create_a_script(editor, tmp_path, name):
    result = await editor.execute(command="write_large", path=str(tmp_path / name), file_text="x")
    assert result.error and not (tmp_path / name).exists()


@pytest.mark.asyncio
async def test_write_large_cannot_replace_a_script(editor, tmp_path):
    script = tmp_path / "run.ps1"
    script.write_text("Write-Output safe", encoding="utf-8")
    result = await editor.execute(command="write_large", path=str(script), file_text="evil")
    assert result.error and script.read_text(encoding="utf-8") == "Write-Output safe"


@pytest.mark.asyncio
async def test_write_large_still_writes_documents(editor, tmp_path):
    result = await editor.execute(
        command="write_large", path=str(tmp_path / "notes.md"), file_text="# hi"
    )
    assert not result.error and (tmp_path / "notes.md").read_text(encoding="utf-8") == "# hi"


@pytest.mark.asyncio
async def test_str_replace_refuses_an_empty_old_str(editor, tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("body", encoding="utf-8")
    result = await editor.execute(command="str_replace", path=str(doc), old_str="", new_str="X")
    assert result.error and doc.read_text(encoding="utf-8") == "body"


@pytest.mark.asyncio
async def test_a_script_can_still_be_edited(editor, tmp_path):
    script = tmp_path / "run.ps1"
    script.write_text("Write-Output one", encoding="utf-8")
    result = await editor.execute(
        command="str_replace", path=str(script), old_str="one", new_str="two"
    )
    assert not result.error and script.read_text(encoding="utf-8") == "Write-Output two"
