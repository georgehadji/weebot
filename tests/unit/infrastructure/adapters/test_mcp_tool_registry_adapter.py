"""Unit tests for RoleBasedToolRegistryAdapter."""

from __future__ import annotations


from weebot.application.ports.mcp_tool_registration_port import McpToolRegistrationPort
from weebot.infrastructure.adapters.mcp_tool_registry_adapter import RoleBasedToolRegistryAdapter


class _FakeRegistry:
    """In-memory registry-like object satisfying the adapter's duck-typed contract."""

    def __init__(self) -> None:
        self._roles: dict[str, list[str]] = {}

    def add_tool_to_role(self, role: str, tool_name: str) -> None:
        if role not in self._roles:
            raise ValueError(f"role {role!r} does not exist")
        if tool_name not in self._roles[role]:
            self._roles[role].append(tool_name)

    def remove_tool_from_role(self, role: str, tool_name: str) -> None:
        if role in self._roles and tool_name in self._roles[role]:
            self._roles[role].remove(tool_name)

    def add_role(self, role: str, tools: list[str]) -> None:
        self._roles[role] = list(tools)

    def list_roles(self) -> list[str]:
        return list(self._roles.keys())


class TestRoleBasedToolRegistryAdapter:
    """Adapter delegates to a registry-like object without importing concrete classes."""

    def test_adapter_satisfies_port(self):
        adapter = RoleBasedToolRegistryAdapter(_FakeRegistry())
        assert isinstance(adapter, McpToolRegistrationPort)

    def test_add_tool_to_existing_role(self):
        registry = _FakeRegistry()
        registry.add_role("admin", ["bash"])
        adapter = RoleBasedToolRegistryAdapter(registry)

        adapter.add_tool_to_role("admin", "mcp__srv__tool")

        assert registry._roles["admin"] == ["bash", "mcp__srv__tool"]

    def test_add_tool_creates_missing_role(self):
        registry = _FakeRegistry()
        adapter = RoleBasedToolRegistryAdapter(registry)

        adapter.add_tool_to_role("admin", "mcp__srv__tool")

        assert registry._roles["admin"] == ["mcp__srv__tool"]

    def test_remove_tool_from_role(self):
        registry = _FakeRegistry()
        registry.add_role("admin", ["bash", "mcp__srv__tool"])
        adapter = RoleBasedToolRegistryAdapter(registry)

        adapter.remove_tool_from_role("admin", "mcp__srv__tool")

        assert registry._roles["admin"] == ["bash"]

    def test_list_roles_delegates(self):
        registry = _FakeRegistry()
        registry.add_role("admin", ["bash"])
        registry.add_role("coder", ["python_execute"])
        adapter = RoleBasedToolRegistryAdapter(registry)

        roles = adapter.list_roles()

        assert sorted(roles) == ["admin", "coder"]

    def test_remove_missing_tool_is_silent(self):
        registry = _FakeRegistry()
        registry.add_role("admin", ["bash"])
        adapter = RoleBasedToolRegistryAdapter(registry)

        # Should not raise even though the tool is not in the role.
        adapter.remove_tool_from_role("admin", "missing")

        assert registry._roles["admin"] == ["bash"]
