"""Schema-guided coercion of tool-call arguments (H16).

Models send ``{"count": "3"}`` where the schema says integer, or ``"[1, 2]"`` where it says
array. ``tool_call_repair`` fixes JSON syntax and tool names; this fixes the types, from the
tool's own parameter schema. Pure: no I/O, and it never invents a required field.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_INT = re.compile(r"^[+-]?\d+$")
_BOOLS = {"true": True, "false": False}


@dataclass(frozen=True)
class Coercion:
    path: str
    rule: str
    before: Any
    after: Any


def coerce_args(
    schema: Mapping[str, Any] | None, args: Mapping[str, Any]
) -> tuple[dict[str, Any], tuple[Coercion, ...]]:
    """Return *args* fitted to *schema*, and what was changed. Unknown keys pass through."""
    log: list[Coercion] = []
    return _object(schema, args, "", log), tuple(log)


def _object(
    schema: Mapping[str, Any] | None, value: Mapping[str, Any], path: str, log: list[Coercion]
) -> dict[str, Any]:
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or ())
    out: dict[str, Any] = {}
    for key, item in value.items():
        here = f"{path}.{key}" if path else key
        sub = props.get(key)
        if sub is None:
            out[key] = item
        elif item is None and key not in required:
            log.append(Coercion(here, "drop_null", None, None))
        else:
            out[key] = _value(sub, item, here, log)
    return out


def _value(schema: Mapping[str, Any], value: Any, path: str, log: list[Coercion]) -> Any:
    kind = schema.get("type")
    if isinstance(kind, list):  # a union: no single rule applies
        return value
    new = value
    if kind == "integer" and isinstance(value, str) and _INT.match(value.strip()):
        new = int(value.strip())
        log.append(Coercion(path, "str_to_int", value, new))
    elif kind == "number" and isinstance(value, str):
        parsed = _float(value)
        if parsed is not None:
            new = int(parsed) if _INT.match(value.strip()) else parsed
            log.append(Coercion(path, "str_to_number", value, new))
    elif kind == "boolean" and isinstance(value, str) and value.strip().lower() in _BOOLS:
        new = _BOOLS[value.strip().lower()]
        log.append(Coercion(path, "str_to_bool", value, new))
    elif kind == "array":
        new = _array(schema, value, path, log)
    elif kind == "object":
        new = _object_value(schema, value, path, log)
    enum = schema.get("enum")
    if enum and isinstance(new, str) and new not in enum:
        canonical = next((e for e in enum if isinstance(e, str) and e.lower() == new.lower()), None)
        if canonical is not None:
            log.append(Coercion(path, "enum_case", new, canonical))
            new = canonical
    return new


def _float(text: str) -> float | None:
    try:
        number = float(text.strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _loads(text: str, opener: str) -> Any:
    stripped = text.strip()
    if not stripped.startswith(opener):
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        return None


def _array(schema: Mapping[str, Any], value: Any, path: str, log: list[Coercion]) -> Any:
    items = value
    if isinstance(value, str):
        parsed = _loads(value, "[")
        if isinstance(parsed, list):
            items = parsed
            log.append(Coercion(path, "json_to_array", value, parsed))
        else:
            items = [value]
            log.append(Coercion(path, "scalar_to_array", value, items))
    elif not isinstance(value, list):
        items = [value]
        log.append(Coercion(path, "scalar_to_array", value, items))
    sub = schema.get("items")
    if isinstance(sub, Mapping):
        return [_value(sub, item, f"{path}[{i}]", log) for i, item in enumerate(items)]
    return items


def _object_value(schema: Mapping[str, Any], value: Any, path: str, log: list[Coercion]) -> Any:
    obj = value
    if isinstance(value, str):
        parsed = _loads(value, "{")
        if not isinstance(parsed, dict):
            return value
        obj = parsed
        log.append(Coercion(path, "json_to_object", value, parsed))
    if isinstance(obj, Mapping):
        return _object(schema, obj, path, log)
    return value
