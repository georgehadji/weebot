"""Unit tests for StrReplaceEditorTool."""
import pytest
from pathlib import Path

from weebot.tools.file_editor import StrReplaceEditorTool


@pytest.fixture
def editor():
    return StrReplaceEditorTool()


@pytest.fixture
def tmp_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line one\nline two\nline three\n", encoding="utf-8")
    return f


@pytest.mark.asyncio
async def test_view_file_with_line_numbers(editor, tmp_file):
    result = await editor.execute("view", str(tmp_file))
    assert not result.is_error
    assert "line one" in result.output
    assert "1:" in result.output  # numbered


@pytest.mark.asyncio
async def test_view_file_not_found_is_error(editor, tmp_path):
    result = await editor.execute("view", str(tmp_path / "missing.txt"))
    assert result.is_error


@pytest.mark.asyncio
async def test_view_directory_lists_contents(editor, tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    result = await editor.execute("view", str(tmp_path))
    assert not result.is_error
    assert "a.py" in result.output
    assert "b.py" in result.output


@pytest.mark.asyncio
async def test_view_range_limits_output(editor, tmp_file):
    result = await editor.execute("view", str(tmp_file), view_range=[1, 2])
    assert "line one" in result.output
    assert "line three" not in result.output


@pytest.mark.asyncio
async def test_create_writes_file(editor, tmp_path):
    new_file = tmp_path / "new.txt"
    result = await editor.execute("create", str(new_file), file_text="hello world")
    assert not result.is_error
    assert new_file.read_text(encoding="utf-8") == "hello world"


@pytest.mark.asyncio
async def test_create_makes_parent_dirs(editor, tmp_path):
    deep_file = tmp_path / "nested" / "dir" / "file.txt"
    result = await editor.execute("create", str(deep_file), file_text="x")
    assert not result.is_error
    assert deep_file.exists()


@pytest.mark.asyncio
async def test_str_replace_replaces_first_occurrence(editor, tmp_file):
    result = await editor.execute(
        "str_replace", str(tmp_file), old_str="line two", new_str="LINE TWO"
    )
    assert not result.is_error
    content = tmp_file.read_text(encoding="utf-8")
    assert "LINE TWO" in content
    assert "line two" not in content


@pytest.mark.asyncio
async def test_str_replace_not_found_is_error(editor, tmp_file):
    result = await editor.execute(
        "str_replace", str(tmp_file), old_str="NONEXISTENT", new_str="x"
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_str_replace_file_not_found_is_error(editor, tmp_path):
    result = await editor.execute(
        "str_replace", str(tmp_path / "missing.txt"), old_str="a", new_str="b"
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_insert_adds_lines(editor, tmp_file):
    result = await editor.execute(
        "insert", str(tmp_file), insert_line=1, new_str="inserted line"
    )
    assert not result.is_error
    lines = tmp_file.read_text(encoding="utf-8").splitlines()
    assert "inserted line" in lines


@pytest.mark.asyncio
async def test_unknown_command_is_error(editor, tmp_path):
    result = await editor.execute("explode", str(tmp_path / "x.txt"))
    assert result.is_error
    assert "Unknown command" in result.error
