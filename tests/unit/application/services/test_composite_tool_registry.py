"""Unit tests for CompositeToolRegistry."""

from __future__ import annotations

from weebot.application.services.composite_tool_registry import CompositeToolRegistry
from weebot.domain.models.composite_tool import CompositeToolSpec, SubToolCall


class TestCompositeToolRegistry:
    """Visibility rules and composite lookup."""

    @staticmethod
    def _make_spec(name: str, hidden: list[str]) -> CompositeToolSpec:
        return CompositeToolSpec(
            name=name,
            description=f"Composite {name}",
            sub_tools=[SubToolCall(tool_name="bash", arguments={"command": "echo ok"})],
            hidden_atomic_tools=hidden,
        )

    def test_register_hides_atomic_tools(self):
        registry = CompositeToolRegistry()
        registry.register(self._make_spec("analyze_and_edit", ["file_editor"]))

        assert registry.is_hidden_atomic("file_editor")
        assert registry.is_visible("bash")

    def test_get_visible_tools_filters_hidden(self):
        registry = CompositeToolRegistry()
        registry.register(self._make_spec("analyze_and_edit", ["file_editor"]))
        all_tools = ["bash", "file_editor", "ping"]

        visible = registry.get_visible_tools(all_tools)

        assert visible == ["bash", "ping"]

    def test_list_composites_returns_names(self):
        registry = CompositeToolRegistry()
        registry.register(self._make_spec("a", []))
        registry.register(self._make_spec("b", []))

        assert sorted(registry.list_composites()) == ["a", "b"]

    def test_get_composite_returns_spec(self):
        registry = CompositeToolRegistry()
        spec = self._make_spec("analyze_and_edit", ["file_editor"])
        registry.register(spec)

        assert registry.get_composite("analyze_and_edit") == spec
        assert registry.get_composite("missing") is None

    def test_multiple_composites_union_hidden_set(self):
        registry = CompositeToolRegistry()
        registry.register(self._make_spec("a", ["x"]))
        registry.register(self._make_spec("b", ["y"]))

        assert not registry.is_visible("x")
        assert not registry.is_visible("y")
