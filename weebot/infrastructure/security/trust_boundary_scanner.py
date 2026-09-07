"""Trust boundary scanner — deferred import to avoid core→infra coupling.

Moved from weebot/core/trust_boundary.py to keep the core layer
free of infrastructure dependencies.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

#: Returned when the scanner could not run at all. It is a detection rather
#: than a None so that the obvious caller — ``if scan_for_injection(x): ...`` —
#: fails CLOSED. The marker key lets a caller that cares tell "we found
#: something" from "we could not look".
SCANNER_UNAVAILABLE: dict[str, Any] = {
    "type": "scanner_unavailable",
    "pattern": "the injection scanner could not run",
    "severity": "critical",
    "match": "",
    "unavailable": True,
}


def scan_for_injection(content: str) -> dict[str, Any] | None:
    """Run the AgentMemorySanitizer against *content*.

    Returns the highest-severity detection dict, or None if clean.

    A failure returns ``SCANNER_UNAVAILABLE``, not None. None is this
    function's word for "I looked and the content is clean"; before this, an
    import error, a missing sanitizer or any exception inside it produced
    exactly that same answer, so a caller gating on the result would have
    treated an unavailable scanner as a clean bill of health. There is no
    caller yet, which is precisely why the failure path has to be right now:
    wiring one up first would ship the fail-open with it.
    """
    try:
        from weebot.infrastructure.security.agent_sanitizer import get_agent_sanitizer

        return get_agent_sanitizer().detect_contamination(content, check_injection=True)
    except Exception:
        _log.warning(
            "trust_boundary: the injection scanner is unavailable — treating content as "
            "contaminated rather than clean",
            exc_info=True,
        )
        return dict(SCANNER_UNAVAILABLE)
