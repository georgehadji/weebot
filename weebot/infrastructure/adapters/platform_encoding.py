"""PlatformEncodingAdapter — safe subprocess output decoding for Windows/Linux.

Windows PowerShell commonly emits CP-1252 bytes (e.g. 0xA7 = §) that crash
bare .decode('utf-8').  This adapter tries UTF-8 first, then falls back
through common Windows codepages, and finally uses 'replace' as last resort.

Usage:
    from weebot.infrastructure.adapters.platform_encoding import safe_decode
    decoded = safe_decode(stdout_bytes)
"""
from __future__ import annotations


# Fallback chain: UTF-8 is the standard; CP-1252 / CP-850 handle Windows
# PowerShell output; latin-1 never fails (maps all 256 bytes).
_DECODE_FALLBACKS = ["utf-8", "cp1252", "cp850", "latin-1"]


def safe_decode(data: bytes) -> str:
    """Decode *data* with automatic encoding fallback.

    Tries UTF-8 first.  On failure, falls back through common Windows
    codepages.  Latin-1 never fails (every byte maps to a Unicode code
    point), so the function is guaranteed to return a string.
    """
    if not data:
        return ""

    for enc in _DECODE_FALLBACKS:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    return data.decode("utf-8", errors="replace")
