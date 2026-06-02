"""CanonicalizerPort — validates and canonicalizes tool calls before execution (Tier 1.1).

Sits between the executor and ToolCollection.  Every tool call passes through
this port for type coercion, default filling, and deterministic-failure blocking.

Implementations:
- ActionCanonicalizer — rule-based using tool contract YAML files
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.canonical import CanonicalizationResult


class CanonicalizerPort(ABC):
    """Validates and canonicalizes a tool call before execution.

    Called by ToolCollection.execute() before dispatching to the tool.
    """

    @abstractmethod
    def canonicalize(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> CanonicalizationResult:
        """Validate and canonicalize *arguments* for *tool_name*.

        Returns a CanonicalizationResult with PASS/BLOCK/FILL_DEFAULT verdict.
        Corrections are applied to the arguments dict before execution.
        """
        ...
