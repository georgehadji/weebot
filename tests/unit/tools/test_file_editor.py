"""Unit tests for StrReplaceEditorTool."""
import pytest
from pathlib import Path


@pytest.fixture
def tmp_file(workspace_editor):
    """Create test file inside workspace."""
    f = workspace_editor / "test.txt"
    f.write_text("line one\nline two\nline three\n", encoding="utf-8")
    return f


@pytest.mark.asyncio
async def test_view_file_with_line_numbers(workspace_editor, tmp_file):
    """Test viewing a file with line numbers."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    result = await editor.execute("view", str(tmp_file))
    assert not result.is_error
    assert "line one" in result.output
    assert "1:" in result.output  # numbered


@pytest.mark.asyncio
async def test_view_file_not_found_is_error(workspace_editor):
    """Test that viewing a non-existent file returns an error."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    result = await editor.execute("view", str(workspace_editor / "missing.txt"))
    assert result.is_error


@pytest.mark.asyncio
async def test_view_directory_lists_contents(workspace_editor):
    """Test that viewing a directory lists its contents."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    (workspace_editor / "a.py").write_text("")
    (workspace_editor / "b.py").write_text("")
    result = await editor.execute("view", str(workspace_editor))
    assert not result.is_error
    assert "a.py" in result.output
    assert "b.py" in result.output


@pytest.mark.asyncio
async def test_view_range_limits_output(tmp_file):
    """Test viewing a specific range of lines."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    result = await editor.execute("view", str(tmp_file), view_range=[1, 2])
    assert "line one" in result.output
    assert "line three" not in result.output


@pytest.mark.asyncio
async def test_create_writes_file(workspace_editor):
    """Test creating a new file."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    new_file = workspace_editor / "new.txt"
    result = await editor.execute("create", str(new_file), file_text="hello world")
    assert not result.is_error
    assert new_file.read_text(encoding="utf-8") == "hello world"


@pytest.mark.asyncio
async def test_create_makes_parent_dirs(workspace_editor):
    """Test that create can make parent directories."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    deep_file = workspace_editor / "nested" / "dir" / "file.txt"
    result = await editor.execute("create", str(deep_file), file_text="x")
    assert not result.is_error
    assert deep_file.exists()


@pytest.mark.asyncio
async def test_str_replace_replaces_first_occurrence(tmp_file):
    """Test str_replace replaces the first occurrence."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    result = await editor.execute(
        "str_replace", str(tmp_file), old_str="line two", new_str="LINE TWO"
    )
    assert not result.is_error
    content = tmp_file.read_text(encoding="utf-8")
    assert "LINE TWO" in content
    assert "line two" not in content


@pytest.mark.asyncio
async def test_str_replace_not_found_is_error(tmp_file):
    """Test that str_replace returns error when string not found."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    result = await editor.execute(
        "str_replace", str(tmp_file), old_str="NONEXISTENT", new_str="x"
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_str_replace_file_not_found_is_error(workspace_editor):
    """Test that str_replace returns error when file not found."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    result = await editor.execute(
        "str_replace", str(workspace_editor / "missing.txt"), old_str="a", new_str="b"
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_insert_adds_lines(tmp_file):
    """Test inserting lines at a specific position."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    result = await editor.execute(
        "insert", str(tmp_file), insert_line=1, new_str="inserted line"
    )
    assert not result.is_error
    lines = tmp_file.read_text(encoding="utf-8").splitlines()
    assert "inserted line" in lines


@pytest.mark.asyncio
async def test_unknown_command_is_error(workspace_editor):
    """Test that unknown commands return an error."""
    from weebot.tools.file_editor import StrReplaceEditorTool
    editor = StrReplaceEditorTool()
    result = await editor.execute("explode", str(workspace_editor / "x.txt"))
    assert result.is_error
    assert "Unknown command" in result.error