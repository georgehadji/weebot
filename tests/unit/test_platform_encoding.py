"""Fuzzing tests for PlatformEncodingAdapter.safe_decode.

Must never raise — the adapter is guaranteed to return a string
for any byte sequence, including random binary and malicious payloads.
"""
from __future__ import annotations

import os
import random

from weebot.infrastructure.adapters.platform_encoding import safe_decode


def test_safe_decode_utf8():
    """Standard UTF-8 must decode correctly."""
    assert safe_decode(b"hello") == "hello"
    assert safe_decode("héllo wörld".encode("utf-8")) == "héllo wörld"


def test_safe_decode_cp1252():
    """CP-1252 bytes (0xA7 = §, common in Windows PowerShell) must not crash."""
    # 0xA7 is invalid start byte in UTF-8
    data = b"hello \xa7 world"
    result = safe_decode(data)
    assert isinstance(result, str)
    assert len(result) > 0


def test_safe_decode_empty():
    """Empty bytes must return empty string."""
    assert safe_decode(b"") == ""
    assert safe_decode(None if hasattr(None, 'decode') else b"") == ""


def test_safe_decode_random_bytes():
    """Any random byte sequence must decode without raising."""
    for _ in range(100):
        length = random.randint(1, 256)
        data = os.urandom(length)
        result = safe_decode(data)
        assert isinstance(result, str)


def test_safe_decode_all_256_bytes():
    """All 256 single-byte values must decode without raising."""
    for byte_val in range(256):
        data = bytes([byte_val])
        result = safe_decode(data)
        assert isinstance(result, str)


def test_safe_decode_mixed_encodings():
    """Mixed UTF-8 + CP-1252 content common in Windows logs."""
    # UTF-8 text followed by CP-1252 smart quotes
    parts = [
        "normal text ".encode("utf-8"),
        b"\x93",  # CP-1252 left double quote
        "more text".encode("utf-8"),
    ]
    data = b"".join(parts)
    result = safe_decode(data)
    assert isinstance(result, str)


def test_safe_decode_null_bytes():
    """Null bytes (common in binary output) must not crash."""
    data = b"text\x00more\x00text"
    result = safe_decode(data)
    assert isinstance(result, str)
