"""Application-layer models.

This package contains models that are first-class application concepts
but do not belong in the domain or infrastructure layers.
"""

from weebot.application.models.tool_collection import ToolCollection

__all__ = ["ToolCollection"]
