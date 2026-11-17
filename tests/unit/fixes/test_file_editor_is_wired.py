"""The container gives `file_editor` its edit-state registry and syntax check (H6).

`StrReplaceEditorTool()` with no collaborators still works, so an unwired editor would
pass every other test while the stale-write guard and the lint never ran in a real flow.
"""

from __future__ import annotations


def _editor():
    from weebot.application.di import Container
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    c = Container()
    c.configure_defaults()
    registry = RoleBasedToolRegistry(wiring=c.tool_wiring)
    return c, registry.create_tool_collection("admin").get_tool("file_editor")


def test_the_admin_editor_is_wired_with_state_and_syntax():
    from weebot.application.ports.syntax_check_port import SyntaxCheckPort
    from weebot.application.services.file_state import FileStateRegistry

    container, editor = _editor()

    assert editor._file_state is container.get(FileStateRegistry)
    assert editor._syntax is container.get(SyntaxCheckPort)


def test_every_collection_shares_one_registry():
    from weebot.application.di import Container
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    c = Container()
    c.configure_defaults()
    registry = RoleBasedToolRegistry(wiring=c.tool_wiring)

    first = registry.create_tool_collection("admin").get_tool("file_editor")
    second = registry.create_tool_collection("admin").get_tool("file_editor")

    assert first._file_state is second._file_state
