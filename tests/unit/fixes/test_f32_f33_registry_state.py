"""F32 and F33 repro: RoleBasedToolRegistry discovery and shared state.

F32: autodiscovery reads `allowed_roles` with getattr on a Pydantic class,
gets the ["*"] fallback for every tool, and returns an empty table.
F33: the default role table is copied shallowly, so add_tool_to_role on one
registry changes every registry built afterwards.
Strict xfail until W5.5 lands; see tasks/icm_fix_plan.md.
"""

import pytest

from weebot.tools.tool_registry import RoleBasedToolRegistry


@pytest.mark.xfail(strict=True, reason="F32: discovery cannot read allowed_roles")
def test_autodiscovery_sees_declared_roles():
    mappings = RoleBasedToolRegistry._build_role_mappings_from_class_map()
    assert mappings, "autodiscovery returned an empty role table"


@pytest.mark.xfail(strict=True, reason="F33: shallow copy of DEFAULT_ROLE_MAPPINGS")
def test_registries_do_not_share_role_lists():
    marker = "f33_marker_tool"
    first = RoleBasedToolRegistry()
    try:
        first.add_tool_to_role("coder", marker)
        assert marker not in RoleBasedToolRegistry().get_tools_for_role("coder")
    finally:
        first.remove_tool_from_role("coder", marker)


@pytest.mark.xfail(strict=True, reason="F33: _TOOL_TIERS is class-level")
def test_registries_do_not_share_tiers():
    first = RoleBasedToolRegistry()
    before = first.get_tool_tier("bash")
    try:
        first.set_tool_tier("bash", "public")
        assert RoleBasedToolRegistry().get_tool_tier("bash") == before
    finally:
        first.set_tool_tier("bash", before)
