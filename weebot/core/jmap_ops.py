"""A JMAP ops request as the server will receive it (pure), for the egress check and the adapter.

Atomic Mail ops are a JMAP method-call list with ``$NAME`` placeholders the adapter fills in
before sending. The egress check must judge that filled-in request: it used to search the raw
text for "EmailSubmission", so ``Email$S/set`` with ``S=Submission`` sent mail unasked
(audit 2026-10-29 R02). Both sides fill placeholders with :func:`fill_vars`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

VAR_PATTERN = re.compile(r"\$([A-Z][A-Z0-9_]*)")
# JMAP's only transmit verb; Email/set alone writes a draft.
_SEND_METHOD = "emailsubmission/set"


def fill_vars(raw: str, values: Mapping[str, Any]) -> str:
    """*raw* with each ``$NAME`` that *values* holds replaced; any other ``$NAME`` is left."""
    return VAR_PATTERN.sub(
        lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), raw
    )


def method_names(ops: str) -> list[str] | None:
    """The method name of every call in a JMAP ops list, or None when *ops* is not one."""
    try:
        calls = json.loads(ops)
    except (TypeError, ValueError):
        return None
    if not isinstance(calls, list):
        return None
    names: list[str] = []
    for call in calls:
        if not (isinstance(call, list) and call and isinstance(call[0], str)):
            return None
        names.append(call[0])
    return names


def sends_mail(ops: Any, values: Mapping[str, Any] | None) -> bool:
    """True when the filled-in request submits mail, or cannot be read (fail closed)."""
    text = ops if isinstance(ops, str) else json.dumps(ops)
    names = method_names(fill_vars(text, values if isinstance(values, Mapping) else {}))
    return names is None or any(name.lower() == _SEND_METHOD for name in names)
