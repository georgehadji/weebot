"""One constant-time compare for API keys, tokens and webhook signatures.

``hmac.compare_digest(str, str)`` raises ``TypeError`` when either string is not ASCII, and
Starlette decodes header bytes as latin-1, so a request header byte 0xE9 arrives as "é". A raw
call turned a wrong key into a 500 that the failed-login throttle never counted. Encoding both
sides first removes the crash and keeps the compare constant-time.

``tests/unit/test_architecture_fitness.py::test_key_compares_go_through_safe_equals`` fails
when ``compare_digest(`` appears anywhere else in ``weebot/``.
"""

from __future__ import annotations

import hmac


def _as_bytes(value: str | bytes) -> bytes:
    return value if isinstance(value, bytes) else value.encode("utf-8", "surrogatepass")


def safe_equals(a: str | bytes | None, b: str | bytes | None) -> bool:
    """True when *a* and *b* are equal. ``None`` on either side is never equal."""
    if a is None or b is None:
        return False
    return hmac.compare_digest(_as_bytes(a), _as_bytes(b))
