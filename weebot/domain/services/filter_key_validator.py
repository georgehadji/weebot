"""FilterKeyValidator — validates filter keys for KnowledgeGraphPort queries.

Ensures that filter keys used in SQL queries are safe alphanumeric
identifiers, preventing SQL injection via malformed property keys.

This validator was extracted from the inline regex in
``postgresql/knowledge_graph.py`` (BUG-01 fix) and promoted to a
shared domain service so both PostgreSQL and SQLite implementations
use the same validation logic consistently.
"""
from __future__ import annotations

import re
from typing import Any

_SAFE_KEY = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_filter_keys(filters: dict[str, Any]) -> dict[str, Any]:
    """Return dict containing only filter keys that are safe for SQL.

    Non-conforming keys (containing special characters, SQL metacharacters,
    or empty strings) are silently dropped with a warning.

    Args:
        filters: Raw filter dict from KnowledgeGraphPort.query().

    Returns:
        Filtered dict containing only keys matching ``^[a-zA-Z_][a-zA-Z0-9_]*$``.
    """
    if filters is None:
        return {}
    import logging
    logger = logging.getLogger(__name__)
    safe = {}
    for k, v in filters.items():
        if _SAFE_KEY.match(k):
            safe[k] = v
        else:
            logger.warning("Dropping unsafe filter key: %s", k)
    return safe
