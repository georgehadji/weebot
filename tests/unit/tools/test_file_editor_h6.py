"""file_editor with the H6 edit pipeline: stale-write guard, patch, fuzzy match, syntax lint."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def editor(workspace_editor):
    from weebot.application.services.file_state import FileStateRegistry
    from weebot.infrastructure.adapters.syntax_check import InProcessSyntaxCheck
    from weebot.tools.file_editor import StrReplaceEditorTool

    return StrReplaceEditorTool(file_state=FileStateRegistry(), syntax=InProcessSyntaxCheck())


@pytest.fixture
def source(workspace_editor):
    f = workspace_editor / "mod.py"
    f.write_text("def f(a):\n    x = a + 1\n    return x\n", encoding="utf-8")
    return f


async def _view(editor, path):
    result = await editor.execute("view", str(path))
    assert not result.is_error
    return result


# ── the stale-write guard ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "extra"),
    [
        ("str_replace", {"old_str": "a + 1", "new_str": "a + 2"}),
        ("insert", {"insert_line": 0, "new_str": "# top"}),
        ("patch", {"hunks": [{"old_str": "a + 1", "new_str": "a + 2"}]}),
        ("write_large", {"file_text": "x = 1\n"}),
    ],
)
async def test_a_write_to_a_file_never_viewed_is_refused(editor, source, command, extra):
    before = source.read_text(encoding="utf-8")

    result = await editor.execute(command, str(source), **extra)

    assert result.is_error and "not viewed" in result.error
    assert source.read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_a_write_after_a_view_is_allowed(editor, source):
    await _view(editor, source)

    result = await editor.execute("str_replace", str(source), old_str="a + 1", new_str="a + 2")

    assert not result.is_error
    assert "a + 2" in source.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_file_changed_after_the_view_is_refused(editor, source):
    await _view(editor, source)
    source.write_text("def f(a):\n    return 0  # changed elsewhere\n", encoding="utf-8")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    result = await editor.execute("str_replace", str(source), old_str="return 0", new_str="return 1")

    assert result.is_error and "changed since you last viewed" in result.error
    assert "return 0" in source.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_touched_but_identical_file_is_still_allowed(editor, source):
    await _view(editor, source)
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    result = await editor.execute("str_replace", str(source), old_str="a + 1", new_str="a + 2")

    assert not result.is_error


@pytest.mark.asyncio
async def test_the_model_may_edit_again_after_its_own_write(editor, source):
    await _view(editor, source)
    await editor.execute("str_replace", str(source), old_str="a + 1", new_str="a + 2")

    again = await editor.execute("str_replace", str(source), old_str="a + 2", new_str="a + 3")

    assert not again.is_error


@pytest.mark.asyncio
async def test_creating_a_new_file_needs_no_view(editor, workspace_editor):
    result = await editor.execute("create", str(workspace_editor / "new.txt"), file_text="hi\n")

    assert not result.is_error
    follow_up = await editor.execute(
        "str_replace", str(workspace_editor / "new.txt"), old_str="hi", new_str="bye"
    )
    assert not follow_up.is_error  # the create recorded the file


@pytest.mark.asyncio
async def test_write_large_to_a_new_path_needs_no_view(editor, workspace_editor):
    result = await editor.execute(
        "write_large", str(workspace_editor / "big.txt"), file_text="a\nb\n"
    )

    assert not result.is_error


@pytest.mark.asyncio
async def test_an_unwired_tool_does_not_track_views(workspace_editor, source):
    from weebot.tools.file_editor import StrReplaceEditorTool

    result = await StrReplaceEditorTool().execute(
        "str_replace", str(source), old_str="a + 1", new_str="a + 2"
    )

    assert not result.is_error


# ── fuzzy str_replace ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_str_replace_tolerates_an_indentation_slip_and_names_the_match(editor, source):
    await _view(editor, source)

    result = await editor.execute(
        "str_replace", str(source), old_str="x = a + 1\nreturn x", new_str="return a + 2"
    )

    assert not result.is_error and "line_trimmed" in result.output
    assert source.read_text(encoding="utf-8") == "def f(a):\n    return a + 2\n"


@pytest.mark.asyncio
async def test_str_replace_refuses_an_ambiguous_old_str(editor, workspace_editor):
    f = workspace_editor / "dup.txt"
    f.write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")
    await _view(editor, f)

    result = await editor.execute("str_replace", str(f), old_str="x = 1", new_str="x = 9")

    assert result.is_error and "2 places" in result.error and "lines 1, 3" in result.error
    assert f.read_text(encoding="utf-8") == "x = 1\ny = 2\nx = 1\n"


@pytest.mark.asyncio
async def test_exact_true_turns_the_fuzzy_chain_off(editor, source):
    await _view(editor, source)

    result = await editor.execute(
        "str_replace",
        str(source),
        old_str="x = a + 1\nreturn x",
        new_str="pass",
        exact=True,
    )

    assert result.is_error and "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_exact_true_keeps_the_old_first_occurrence_behaviour(editor, workspace_editor):
    f = workspace_editor / "dup.txt"
    f.write_text("x = 1\nx = 1\n", encoding="utf-8")
    await _view(editor, f)

    result = await editor.execute(
        "str_replace", str(f), old_str="x = 1", new_str="x = 9", exact=True
    )

    assert not result.is_error
    assert f.read_text(encoding="utf-8") == "x = 9\nx = 1\n"


# ── patch ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_applies_every_hunk_in_one_write(editor, source):
    await _view(editor, source)

    result = await editor.execute(
        "patch",
        str(source),
        hunks=[
            {"old_str": "def f(a):", "new_str": "def f(a, b=0):"},
            {"old_str": "a + 1", "new_str": "a + b"},
        ],
    )

    assert not result.is_error and "2 hunk(s)" in result.output
    assert source.read_text(encoding="utf-8") == (
        "def f(a, b=0):\n    x = a + b\n    return x\n"
    )


@pytest.mark.asyncio
async def test_patch_with_one_bad_hunk_leaves_the_file_untouched(editor, source):
    await _view(editor, source)
    before = source.read_text(encoding="utf-8")

    result = await editor.execute(
        "patch",
        str(source),
        hunks=[
            {"old_str": "a + 1", "new_str": "a + 2"},
            {"old_str": "no such text anywhere", "new_str": "x"},
        ],
    )

    assert result.is_error
    assert "Hunk 2 failed" in result.error and "nothing was written" in result.error
    assert source.read_text(encoding="utf-8") == before
    assert not list(source.parent.glob("*.tmp"))


@pytest.mark.asyncio
@pytest.mark.parametrize("hunks", [None, [], "x", [{"old_str": "a"}], [3]])
async def test_patch_rejects_malformed_hunks(editor, source, hunks):
    await _view(editor, source)

    result = await editor.execute("patch", str(source), hunks=hunks)

    assert result.is_error


# ── syntax lint ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_python_syntax_error_after_a_write_is_reported_and_the_write_stands(
    editor, source
):
    await _view(editor, source)

    result = await editor.execute("str_replace", str(source), old_str="return x", new_str="return (")

    assert not result.is_error
    assert "Syntax warning" in result.output and "Python syntax error" in result.output
    assert "return (" in source.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_clean_write_carries_no_warning(editor, source):
    await _view(editor, source)

    result = await editor.execute("str_replace", str(source), old_str="a + 1", new_str="a + 2")

    assert "Syntax warning" not in result.output


@pytest.mark.asyncio
async def test_create_lints_a_new_json_file(editor, workspace_editor):
    result = await editor.execute(
        "create", str(workspace_editor / "cfg.json"), file_text='{"a": 1,}'
    )

    assert not result.is_error and "JSON error" in result.output
