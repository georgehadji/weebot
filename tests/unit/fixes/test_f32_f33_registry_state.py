"""F32 and F33: RoleBasedToolRegistry discovery and shared state (W5.5).

F32: autodiscovery read `allowed_roles` with getattr on a Pydantic class, got
the ["*"] fallback for every tool and returned an empty table, so the registry
always fell back to DEFAULT_ROLE_MAPPINGS. Fixed, it would have replaced the
role table and put exec tools in every role. Decision (W5.5, 2026-10-23): the
dead branch is deleted; DEFAULT_ROLE_MAPPINGS is the one role table.
F33: the default role table was copied shallowly, so changing one registry
changed every registry built afterwards. F34: see the last test.
"""

from weebot.tools.tool_registry import RoleBasedToolRegistry


def test_the_role_table_is_the_default_table():
    assert not hasattr(RoleBasedToolRegistry, "_build_role_mappings_from_class_map")
    registry = RoleBasedToolRegistry()
    assert registry.role_mappings == RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS


def test_registries_do_not_share_role_lists():
    marker = "f33_marker_tool"
    first = RoleBasedToolRegistry()
    try:
        first.add_tool_to_role("coder", marker)
        assert marker not in RoleBasedToolRegistry().get_tools_for_role("coder")
        assert marker not in RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS["coder"]
    finally:
        first.remove_tool_from_role("coder", marker)


def test_the_unenforced_tier_system_is_gone():
    """F34 (W5.5): tool capability tiers were written (the MCP bridge set them)
    but nothing enforced them: `get_tools_for_role_with_gate` had no caller.
    Wiring it as written would have stripped `terminate` (privileged) from every
    role and `bash` from every background run. The guard chain is what gates
    execution; the tier table, the gate and `CapabilityTier` were deleted."""
    import importlib.util

    for attr in ("get_tool_tier", "set_tool_tier", "get_tools_for_role_with_gate", "_TOOL_TIERS"):
        assert not hasattr(RoleBasedToolRegistry, attr), attr
    assert importlib.util.find_spec("weebot.application.services.capability_gate") is None
    assert importlib.util.find_spec("weebot.domain.models.capability_tier") is None
