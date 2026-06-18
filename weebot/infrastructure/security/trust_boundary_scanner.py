"""Trust boundary scanner — deferred import to avoid core→infra coupling.

Moved from weebot/core/trust_boundary.py to keep the core layer
free of infrastructure dependencies.
"""
from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger(__name__)


def scan_for_injection(content: str) -> Optional[dict]:
    """Run the dormant AgentMemorySanitizer against *content*.

    Returns the highest-severity detection dict, or None if clean.
    Import is deferred to avoid circular imports at module load time.
    """
    try:
        from weebot.infrastructure.security.agent_sanitizer import get_agent_sanitizer
        return get_agent_sanitizer().detect_contamination(content, check_injection=True)
    except Exception:
        _log.debug("trust_boundary: sanitizer unavailable, skipping scan", exc_info=True)
        return None
