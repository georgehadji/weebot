"""safe_equals: a constant-time key compare that does not crash on non-ASCII text.

``hmac.compare_digest(str, str)`` raises ``TypeError`` for a non-ASCII string, and Starlette
decodes header bytes as latin-1, so a request header byte 0xE9 arrives as "é". A raw call on
that value turned a wrong key into a 500 outside the failed-login throttle. Every key compare
goes through ``safe_equals`` instead.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from weebot.core.secret_compare import safe_equals


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("secret", "secret", True),
        ("secret", "Secret", False),
        ("secret", "secre", False),
        ("", "", True),
        ("é", "é", True),
        ("é", "e", False),
        ("clé", "cle", False),
        ("😀", "😀", True),
        ("😀", "x", False),
        (None, "secret", False),
        ("secret", None, False),
        (None, None, False),
        (b"secret", "secret", True),
        ("secret", b"secret", True),
    ],
)
def test_safe_equals_table(a, b, expected):
    assert safe_equals(a, b) is expected


@given(st.text(), st.text())
def test_safe_equals_agrees_with_equality_and_never_raises(a, b):
    assert safe_equals(a, b) is (a == b)
