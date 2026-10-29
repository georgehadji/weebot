"""S7 (remaining-work plan 2026-10-29): a status code inside an id is not a status code.

The classifier searched for bare digits, so ``req_4012ab`` read as HTTP 401 (AUTH: fail
fast, no retry) and a trace id holding ``429`` or ``500`` picked the wrong recovery. A
code now counts only when it stands alone, not glued to letters, digits, ``_`` or ``-``.
"""

from __future__ import annotations

import pytest

from weebot.core.error_classifier import ErrorCategory, ErrorClassifier


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("upstream reset, request id req_4012ab", ErrorCategory.NETWORK),
        ("peer closed, trace 7f4290a1-c429-11ee", ErrorCategory.NETWORK),
        ("connection dropped, span-id 1500ab", ErrorCategory.NETWORK),
        ("Error code: 429 - too fast", ErrorCategory.RATE_LIMIT),
        ("HTTP 401: Unauthorized", ErrorCategory.AUTH),
        ("status=403", ErrorCategory.AUTH),
        ("Error code: 400 - {'error': 'x'}", ErrorCategory.BAD_REQUEST),
        ("HTTP 503 from upstream", ErrorCategory.MODEL_UNAVAILABLE),
        ("got (500) from provider", ErrorCategory.SERVER_ERROR),
        ("bad gateway 502", ErrorCategory.SERVER_ERROR),
    ],
)
def test_codes_count_only_on_their_own(message, category):
    assert ErrorClassifier.classify(ConnectionError(message)) == category
