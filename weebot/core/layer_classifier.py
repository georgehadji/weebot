"""Layer classifier — maps module paths to Clean Architecture layers.

Introduced to classify the 128 unclassified modules discovered by the
dependency-graph analysis (Task 3 of the empirical run, June 2026).
Centralizes layer classification so that linters, architecture validators,
and analysis tools share one mapping.
"""
from __future__ import annotations

# Ordered by specificity (longer prefixes first) so that
# "weebot/domain/models/" matches before "weebot/domain/" matches before
# "weebot/" which matches everything.
_LAYER_RULES: list[tuple[str, str]] = [
    # Domain — innermost layer, pure business logic
    ("weebot/domain/", "domain"),
    # Application — orchestration, use cases, CQRS, DI
    ("weebot/application/ports/", "application"),
    ("weebot/application/services/", "application"),
    ("weebot/application/agents/", "application"),
    ("weebot/application/flows/", "application"),
    ("weebot/application/cqrs/", "application"),
    ("weebot/application/di/", "application"),
    ("weebot/application/eval/", "application"),
    ("weebot/application/", "application"),
    # Infrastructure — adapters, persistence, MCP, observability
    ("weebot/infrastructure/", "infrastructure"),
    ("weebot/tools/", "infrastructure"),               # tool implementations
    ("weebot/qmd_integration/", "infrastructure"),     # QMD adapter
    ("weebot/scheduling/", "infrastructure"),           # cron/scheduling
    ("weebot/skills/", "application"),                  # skill definitions
    # Interfaces — CLI, Web, MCP server
    ("weebot/interfaces/", "interfaces"),
    ("weebot/mcp/", "interfaces"),                      # MCP server
    ("weebot/templates/", "interfaces"),                # UI templates
    # Core — cross-cutting concerns
    ("weebot/core/", "core"),
    ("weebot/config/", "core"),                         # configuration
    # Agents — legacy agent orchestration (maps to application)
    ("weebot/agents/", "application"),
    ("weebot/agent_core_v2", "application"),
    # Tests — separate layer
    ("tests/", "tests"),
]


def layer_for_module(module_path: str) -> str:
    """Return the Clean Architecture layer for a module path.

    Args:
        module_path: Path relative to project root, e.g.
            ``"weebot/domain/models/plan.py"``.

    Returns:
        One of ``"domain"``, ``"application"``, ``"infrastructure"``,
        ``"interfaces"``, ``"core"``, ``"tests"``, or ``"unknown"``.
    """
    # Normalize: strip leading ./, convert backslashes, lowercase
    normalized = module_path.replace("\\", "/").lstrip("./")
    for prefix, layer in _LAYER_RULES:
        if normalized.startswith(prefix):
            return layer
    return "unknown"


def layer_counts(paths: list[str]) -> dict[str, int]:
    """Return per-layer file counts for a list of module paths.

    Args:
        paths: Module paths (any format — normalized internally).

    Returns:
        Dict mapping layer name to file count, sorted by count descending.
    """
    counts: dict[str, int] = {}
    for p in paths:
        layer = layer_for_module(p)
        counts[layer] = counts.get(layer, 0) + 1
    # Sort by count descending
    return dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))
