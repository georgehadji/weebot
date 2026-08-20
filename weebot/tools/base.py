"""BaseTool protocol — OpenManus-style function-calling tools for weebot.

``BaseTool`` now lives in ``weebot.domain.models.base_tool`` (ARCH-AUDIT-V2 B5).
This module re-exports it for backward compatibility — all 45+ concrete tools
continue to import from ``weebot.tools.base`` unchanged.
"""

from __future__ import annotations

# ── Domain-level contract ──────────────────────────────────────────
from weebot.domain.models.base_tool import BaseTool  # noqa: F401 — re-export

# ToolResult is now a domain-level value object — re-exported here for
# backward compatibility so existing tools don't need import changes.
from weebot.domain.models.tool_result import ToolResult  # noqa: F401 — re-export

# ToolCollection has been promoted to weebot.application.models.tool_collection.
# This module-level __getattr__ provides a lazy backward-compatible re-export
# that avoids a circular import between tools/base and application/models.


def __getattr__(name: str):
    if name == "ToolCollection":
        from weebot.application.models.tool_collection import ToolCollection as _ToolCollection

        return _ToolCollection
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
