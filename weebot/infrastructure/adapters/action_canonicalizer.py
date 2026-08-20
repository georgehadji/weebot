"""ActionCanonicalizer — rule-based implementation of CanonicalizerPort (Tier 1.1).

Validates and corrects tool-call arguments against each tool's own JSON-Schema
parameter spec before dispatch: fills schema defaults for missing arguments,
coerces primitive types the LLM commonly stringifies (numbers/booleans sent
as strings), and blocks calls missing a required argument with no default
when ``strict_mode`` is enabled.

Deliberately independent of the Environment Contract YAML files
(``config/contracts/``, Tier 3.2, loaded by ``ContractLoader``) — this
canonicalizes purely from each tool's own ``parameters`` JSON Schema, which
every tool has. Contract files only exist for a subset of tools and drive
``ContractLoader.enhance_description()`` (prompt-level pitfall warnings),
not argument coercion — merging the two would make canonicalization behave
differently depending on whether a contract file happens to exist.
"""

from __future__ import annotations

import logging
from typing import Any
from collections.abc import Sequence

from weebot.application.ports.canonicalizer_port import CanonicalizerPort
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.canonical import CanonicalizationResult, CanonicalizationVerdict

logger = logging.getLogger(__name__)

_TRUE_STRINGS = {"true", "yes", "1", "on"}
_FALSE_STRINGS = {"false", "no", "0", "off"}


class ActionCanonicalizer(CanonicalizerPort):
    """Validates and canonicalizes tool-call arguments against tool JSON schemas."""

    def __init__(
        self, tools: Sequence[BaseTool] = (), strict_mode: bool = False, coerce_types: bool = True
    ) -> None:
        self._schemas: dict[str, dict[str, Any]] = {
            t.name: t.parameters for t in tools if isinstance(t.parameters, dict)
        }
        self._strict_mode = strict_mode
        self._coerce_types = coerce_types

    def canonicalize(self, tool_name: str, arguments: dict[str, Any]) -> CanonicalizationResult:
        schema = self._schemas.get(tool_name)
        if not schema:
            return CanonicalizationResult(
                verdict=CanonicalizationVerdict.PASS,
                original_args=dict(arguments),
                corrected_args=dict(arguments),
            )

        properties: dict[str, Any] = schema.get("properties", {}) or {}
        required: list[str] = list(schema.get("required", []) or [])
        corrected = dict(arguments)
        changes: list[str] = []

        for prop_name, prop_schema in properties.items():
            if (
                prop_name not in corrected
                and isinstance(prop_schema, dict)
                and "default" in prop_schema
            ):
                corrected[prop_name] = prop_schema["default"]
                changes.append(f"filled default for '{prop_name}'")

        if self._coerce_types:
            for prop_name, value in list(corrected.items()):
                prop_schema = properties.get(prop_name)
                if not isinstance(prop_schema, dict):
                    continue
                coerced, changed = _coerce(value, prop_schema.get("type"))
                if changed:
                    corrected[prop_name] = coerced
                    changes.append(f"coerced '{prop_name}' to {prop_schema.get('type')}")

        missing_required = [name for name in required if name not in corrected]
        if missing_required and self._strict_mode:
            reason = (
                f"missing required argument(s) for '{tool_name}': " f"{', '.join(missing_required)}"
            )
            return CanonicalizationResult(
                verdict=CanonicalizationVerdict.BLOCK,
                original_args=dict(arguments),
                corrected_args=corrected,
                changes=changes,
                block_reason=reason,
            )

        verdict = CanonicalizationVerdict.FILL_DEFAULT if changes else CanonicalizationVerdict.PASS
        return CanonicalizationResult(
            verdict=verdict,
            original_args=dict(arguments),
            corrected_args=corrected,
            changes=changes,
        )


def _coerce(value: Any, json_type: Any) -> tuple[Any, bool]:
    """Best-effort coercion of *value* to *json_type*. Returns ``(value, changed)``."""
    if json_type is None or isinstance(value, bool):
        # bool is an int subclass — never reinterpret an already-bool value.
        return value, False

    types = json_type if isinstance(json_type, list) else [json_type]

    if "string" in types and isinstance(value, (int, float)):
        return str(value), True

    if isinstance(value, str):
        stripped = value.strip()
        if "boolean" in types:
            lowered = stripped.lower()
            if lowered in _TRUE_STRINGS:
                return True, True
            if lowered in _FALSE_STRINGS:
                return False, True
        if "integer" in types:
            try:
                return int(stripped), True
            except ValueError:
                pass
        if "number" in types:
            try:
                return float(stripped), True
            except ValueError:
                pass

    return value, False
