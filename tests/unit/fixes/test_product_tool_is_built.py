"""The `product` tool is built for the roles that list it (F47).

`ProductTool(repo)` needs a ToolRepositoryPort, but `tool_wiring` gave it no
collaborator, so the bare `ProductTool()` raised TypeError and the registry
skipped it with a debug log: documentation and product_manager lost the tool.
"""

from __future__ import annotations


def test_documentation_role_gets_the_product_tool():
    from weebot.application.di import Container
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    c = Container()
    c.configure_defaults()
    assert "product" in RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS["documentation"]
    registry = RoleBasedToolRegistry(wiring=c.tool_wiring)
    assert registry.create_tool_collection("documentation").get_tool("product") is not None
