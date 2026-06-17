"""Secret Redaction — detects and redacts secrets in tool output and logs.

Patterns covered:
- PANs (credit card numbers): 16 digits, Luhn-checked
- CVV/CVC: 3-4 digit codes
- API keys: Stripe (sk_live_*, rk_live_*, whsec_*)
- AWS: AKIA keys
- JWT tokens
- High-entropy strings (Shannon entropy > threshold)
- Generic bearer tokens and passwords

Usage:
    redactor = SecretRedactor()
    safe_text = redactor.redact(suspicious_text)
"""
from __future__ import annotations

import math
import re
from typing import Any

from weebot.config.settings import WeebotSettings


class SecretRedactor:
    """Redacts secrets from text using pattern matching and entropy analysis.

    Applies in order:
    1. Known patterns (PANs, API keys, tokens)
    2. High-entropy string detection (configurable threshold)
    """

    # Patterns compiled once at class level
    _PAN_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
    _CVV_RE = re.compile(r"\b\d{3,4}\b")
    _STRIPE_KEY_RE = re.compile(
        r"(?:sk_live|rk_live|whsec|whsec_|sk_test|rk_test)_[A-Za-z0-9]{24,}"
    )
    _AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
    _JWT_RE = re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    )
    _BEARER_RE = re.compile(
        r"Bearer\s+[A-Za-z0-9._\-+/=]{20,}", re.IGNORECASE
    )
    _PASSWORD_RE = re.compile(
        r'(?:password|passwd|pwd|secret)\s*[:=]\s*["\']?([^\s"\'&|;]{4,})["\']?',
        re.IGNORECASE,
    )
    _API_KEY_GENERIC = re.compile(
        r"(?:api[_-]?key|apikey|api[_-]?secret)\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})[\"']?",
        re.IGNORECASE,
    )

    def __init__(self, enabled: bool = True, entropy_threshold: float = 3.5) -> None:
        self._enabled = enabled
        self._entropy_threshold = entropy_threshold

    @classmethod
    def from_settings(cls) -> "SecretRedactor":
        """Create from WeebotSettings."""
        try:
            settings = WeebotSettings()
            return cls(
                enabled=settings.secret_redaction_enabled,
                entropy_threshold=settings.secret_redaction_entropy_threshold,
            )
        except Exception:
            return cls()

    def redact(self, text: str) -> str:
        """Redact secrets from *text*.

        Args:
            text: Raw text that may contain secrets.

        Returns:
            Text with secrets replaced by [REDACTED].
        """
        if not self._enabled or not text:
            return text

        result = text

        # 1. Known patterns (highest confidence)
        result = self._STRIPE_KEY_RE.sub("[STRIPE_KEY_REDACTED]", result)
        result = self._AWS_KEY_RE.sub("[AWS_KEY_REDACTED]", result)
        result = self._JWT_RE.sub("[JWT_REDACTED]", result)
        result = self._BEARER_RE.sub("[BEARER_TOKEN_REDACTED]", result)
        result = self._PASSWORD_RE.sub(r"password=[REDACTED]", result)
        result = self._API_KEY_GENERIC.sub(r"\1=[REDACTED]", result)

        # 2. PANs (credit card numbers) — validated with Luhn check
        result = self._redact_pans(result)

        # 3. CVV codes
        result = self._CVV_RE.sub("[CVV_REDACTED]", result)

        # 4. High-entropy strings
        result = self._redact_high_entropy(result)

        return result

    def _redact_pans(self, text: str) -> str:
        """Find and redact valid PANs using Luhn algorithm."""

        def _luhn_check(digits: str) -> bool:
            """Validate a PAN using the Luhn algorithm."""
            clean = digits.replace(" ", "").replace("-", "")
            if not clean.isdigit() or len(clean) < 13 or len(clean) > 19:
                return False
            total = 0
            reverse = clean[::-1]
            for i, d in enumerate(reverse):
                n = int(d)
                if i % 2 == 1:
                    n *= 2
                    if n > 9:
                        n -= 9
                total += n
            return total % 10 == 0

        def _replace_pan(match: re.Match) -> str:
            candidate = match.group(0)
            clean = candidate.replace(" ", "").replace("-", "")
            if _luhn_check(clean):
                return "[PAN_REDACTED]"
            return candidate

        return self._PAN_RE.sub(_replace_pan, text)

    def _redact_high_entropy(self, text: str) -> str:
        """Redact high-entropy strings that look like secrets.

        Analyzes space-separated tokens; if a token has Shannon entropy
        above threshold and looks like a secret (alphanumeric, mixed case,
        long enough), it gets redacted.
        """

        def _shannon_entropy(s: str) -> float:
            if not s:
                return 0.0
            entropy = 0.0
            length = len(s)
            for c in set(s):
                p = s.count(c) / length
                if p > 0:
                    entropy -= p * math.log2(p)
            return entropy

        words = text.split()
        result_words: list[str] = []
        for word in words:
            # Only check reasonably long alphanumeric tokens
            if len(word) >= 20 and word.isascii() and not word.isalpha():
                entropy = _shannon_entropy(word)
                if entropy >= self._entropy_threshold:
                    # Check it's not already a redaction marker
                    if not word.startswith("["):
                        result_words.append("[HIGH_ENTROPY_REDACTED]")
                        continue
            result_words.append(word)

        return " ".join(result_words)

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact secrets in a dictionary.

        Useful for sanitizing API responses before logging.
        """
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.redact(value)
            elif isinstance(value, dict):
                result[key] = self.redact_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self.redact_dict(v) if isinstance(v, dict)
                    else self.redact(v) if isinstance(v, str)
                    else v
                    for v in value
                ]
            else:
                result[key] = value
        return result
