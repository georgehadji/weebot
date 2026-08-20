"""CompositeToolRegistry — manages composite tools and visibility rules."""

from __future__ import annotations

from weebot.domain.models.composite_tool import CompositeToolSpec


class CompositeToolRegistry:
    """Manages composite tools and visibility rules for the MCP surface.

    Composite tools encapsulate multi-step workflows.  When a composite is
    registered, the atomic tools it covers can be hidden from ``list_tools``
    so clients see a smaller, higher-level catalog.
    """

    def __init__(self) -> None:
        self._composites: dict[str, CompositeToolSpec] = {}
        self._hidden_atomic: set[str] = set()

    def register(self, spec: CompositeToolSpec) -> None:
        """Register a composite tool and hide its covered atomic tools."""
        self._composites[spec.name] = spec
        self._hidden_atomic.update(spec.hidden_atomic_tools)

    def is_visible(self, tool_name: str) -> bool:
        """Return True if *tool_name* should appear in ``list_tools``."""
        return tool_name not in self._hidden_atomic

    def get_visible_tools(self, all_tools: list[str]) -> list[str]:
        """Filter *all_tools* to only those not hidden by a composite."""
        return [t for t in all_tools if self.is_visible(t)]

    def get_composite(self, name: str) -> CompositeToolSpec | None:
        """Return the composite spec named *name*, or None."""
        return self._composites.get(name)

    def list_composites(self) -> list[str]:
        """Return names of all registered composite tools."""
        return list(self._composites.keys())

    def is_hidden_atomic(self, tool_name: str) -> bool:
        """Return True if *tool_name* is hidden because a composite covers it."""
        return tool_name in self._hidden_atomic
