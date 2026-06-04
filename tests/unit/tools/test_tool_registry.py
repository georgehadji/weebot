"""Tests for RoleBasedToolRegistry."""

import pytest

from weebot.tools.tool_registry import RoleBasedToolRegistry


class TestRoleBasedToolRegistry:
    """Test cases for role-based tool access control."""

    def test_get_tools_for_valid_role(self):
        """Test retrieving tools for a valid role."""
        registry = RoleBasedToolRegistry()

        researcher_tools = registry.get_tools_for_role("researcher")
        assert isinstance(researcher_tools, list)
        assert len(researcher_tools) > 0
        assert "web_search" in researcher_tools
        assert "file_editor" in researcher_tools

    def test_get_tools_for_invalid_role_raises_error(self):
        """Test that invalid role raises ValueError."""
        registry = RoleBasedToolRegistry()

        with pytest.raises(ValueError) as exc_info:
            registry.get_tools_for_role("invalid_role_xyz")

        assert "Unknown role" in str(exc_info.value)

    def test_validate_tool_for_role(self):
        """Test tool validation for a role."""
        registry = RoleBasedToolRegistry()

        # Researcher should have web_search
        assert registry.validate_tool_for_role("researcher", "web_search") is True

        # Analyst should have python_tool
        assert registry.validate_tool_for_role("analyst", "python_tool") is True

        # Researcher should NOT have python_tool
        assert registry.validate_tool_for_role("researcher", "python_tool") is False

        # Invalid role should return False (not raise)
        assert registry.validate_tool_for_role("invalid_role", "web_search") is False

    def test_add_role(self):
        """Test adding a new role with tools."""
        registry = RoleBasedToolRegistry()
        custom_tools = ["custom_tool_1", "custom_tool_2"]

        registry.add_role("custom_specialist", custom_tools)

        assert registry.validate_tool_for_role("custom_specialist", "custom_tool_1")
        assert registry.validate_tool_for_role("custom_specialist", "custom_tool_2")

    def test_add_tool_to_existing_role(self):
        """Test adding a single tool to an existing role."""
        registry = RoleBasedToolRegistry()

        # Verify researcher doesn't have "new_tool" initially
        researcher_tools = registry.get_tools_for_role("researcher")
        assert "new_tool" not in researcher_tools

        # Add tool
        registry.add_tool_to_role("researcher", "new_tool")

        # Verify it's there now
        assert registry.validate_tool_for_role("researcher", "new_tool")

    def test_list_roles(self):
        """Test listing all available roles."""
        registry = RoleBasedToolRegistry()
        roles = registry.list_roles()

        assert isinstance(roles, list)
        assert "researcher" in roles
        assert "analyst" in roles
        assert "automation" in roles
        assert "admin" in roles

    def test_admin_role_has_all_tools(self):
        """Test that admin role has comprehensive tool access."""
        registry = RoleBasedToolRegistry()
        admin_tools = registry.get_tools_for_role("admin")
        all_tools = registry.list_all_tools()

        # Admin should have access to most tools
        assert len(admin_tools) >= len(all_tools) - 3  # Allow some exclusions
