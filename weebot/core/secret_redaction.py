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
    # A CVV cannot be recognised from digits alone — it is three or four digits,
    # and so is every port, HTTP status, year, line number and millisecond
    # count. The bare `\b\d{3,4}\b` this replaces redacted all of them:
    # `port 8080` -> `port [CVV_REDACTED]`, `HTTP 404` -> `HTTP [CVV_REDACTED]`,
    # `year 2026`, `took 250 ms`. Context is the only thing that makes the
    # detection possible, so context is now required.
    _CVV_RE = re.compile(
        r"\b(cvv2?|cvc2?|csc|card\s*(?:security|verification)\s*(?:code|value))"
        r"\s*[:=]?\s*(\d{3,4})\b",
        re.IGNORECASE,
    )
    _STRIPE_KEY_RE = re.compile(
        r"(?:sk_live|rk_live|whsec|whsec_|sk_test|rk_test)_[A-Za-z0-9]{24,}"
    )
    _AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
    _JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
    _BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]{20,}", re.IGNORECASE)
    _PASSWORD_RE = re.compile(
        r'(password|passwd|pwd|secret)\s*[:=]\s*["\']?([^\s"\'&|;]{4,})["\']?', re.IGNORECASE
    )
    _API_KEY_GENERIC = re.compile(
        r"(?:api[_-]?key|apikey|api[_-]?secret)\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})[\"']?",
        re.IGNORECASE,
    )

    # Shapes that are high-entropy and are never secrets in this codebase. The
    # entropy heuristic cannot tell them from a token, because there is nothing
    # to tell: a 40-character hex digest and a 40-character key have the same
    # character distribution.
    _NOT_A_SECRET_SHAPES = (
        # A filesystem path, optionally with the `:line` / `:line:col` suffix
        # that grep, tracebacks and every linter emit. Without the suffix,
        # `some/path/file.py:123` was still redacted — which is the single
        # commonest shape in a coding agent's tool output.
        re.compile(r"^[/~.]?[\w.~-]*/[\w./~-]+(?::\d+)*:?$"),
        re.compile(r"^(?:[0-9a-f]{7,}|sha\d+:[0-9a-f]+)$", re.IGNORECASE),  # hex digest / git sha
        re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.IGNORECASE),  # uuid
    )

    def __init__(
        self,
        enabled: bool = True,
        entropy_threshold: float = 3.5,
        enable_entropy: bool = False,
    ) -> None:
        self._enabled = enabled
        self._entropy_threshold = entropy_threshold
        self._enable_entropy = enable_entropy

    @classmethod
    def from_settings(cls) -> SecretRedactor:
        """Create from WeebotSettings, with the entropy pass OFF.

        `enable_entropy` defaults to False and `from_settings` does not turn it
        on, because measurement says it cannot be used on this codebase's tool
        output. Against text a coding agent actually produces:

            commit b91a29ae97138...      -> [HIGH_ENTROPY_REDACTED]
            /home/user/weebot/.../x.py   -> [HIGH_ENTROPY_REDACTED]
            session a779ecbb-1b3a-...    -> [HIGH_ENTROPY_REDACTED]
            sha256:9f86d081884c7d6...    -> [HIGH_ENTROPY_REDACTED]

        Redacting file paths and commit SHAs from tool output would leave the
        agent unable to work, and that is not a threshold to tune: a hex digest
        and a hex key have the same character distribution, so no threshold
        separates them. `_NOT_A_SECRET_SHAPES` removes the specific shapes above
        for anyone who does turn the pass on, but the residue is still a
        heuristic that redacts by *appearance*, so it stays opt-in.

        The PATTERN passes carry no such risk and are wired in — see
        `weebot.core.credential_sanitizer.sanitize`.
        """
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
        # Keep the label the text actually used. The old replacement was the
        # literal `password=[REDACTED]`, so `secret: x` and `pwd=x` both came
        # out claiming to be a password — a sanitiser rewriting the surrounding
        # log rather than only the secret in it.
        result = self._PASSWORD_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", result)
        result = self._API_KEY_GENERIC.sub(r"[API_KEY_REDACTED]", result)

        # 2. PANs (credit card numbers) — validated with Luhn check
        result = self._redact_pans(result)

        # 3. CVV codes, only where the text says that is what they are
        result = self._CVV_RE.sub(lambda m: f"{m.group(1)}=[CVV_REDACTED]", result)

        # 4. High-entropy strings — opt-in; see `from_settings` for why.
        if self._enable_entropy:
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
        """Redact high-entropy tokens, preserving the text around them.

        Two things this used to get wrong, both of which made it unsafe to
        wire into a log pipeline:

        **It destroyed the text's shape.** `text.split()` then `" ".join(...)`
        collapses every newline, tab and run of spaces into one space, so a
        multi-line log came out as a single line — a sanitiser reformatting
        the record it was only supposed to redact. Splitting on a *captured*
        whitespace group keeps the separators exactly as they were.

        **Its own markers fed back into it.** The guard skipped a token that
        `startswith("[")`, which misses a marker substituted into the middle
        of one. `file.py:123` became `file.py:[CVV_REDACTED]` — 22 characters,
        not alphabetic — which then tripped the 20-character entropy rule and
        vanished entirely as `[HIGH_ENTROPY_REDACTED]`. A source location was
        redacted because an earlier redaction had lengthened it. Any token
        already carrying a marker is now left alone.
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

        # A capturing split keeps the whitespace runs as their own pieces, so
        # rejoining reproduces the original layout byte for byte.
        pieces = re.split(r"(\s+)", text)
        result: list[str] = []
        for piece in pieces:
            if (
                len(piece) >= 20
                and piece.isascii()
                and not piece.isalpha()
                and "_REDACTED]" not in piece
                and not any(shape.match(piece) for shape in self._NOT_A_SECRET_SHAPES)
                and _shannon_entropy(piece) >= self._entropy_threshold
            ):
                result.append("[HIGH_ENTROPY_REDACTED]")
                continue
            result.append(piece)

        return "".join(result)

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact secrets in a mapping, and in its keys.

        Four shapes used to pass through untouched while the result was
        presented as sanitised — measured, all four:

        =========================  =========================================
        `{"sk_live_AAA…": "..."}`  a secret as a **key**; keys were never
                                   looked at
        `b"password=hunter2"`      **bytes**; only `str` was handled
        `[[{"note": "pw=x"}]]`     a dict below **two** list levels; exactly
                                   one level was recursed
        `("password=hunter2",)`    a **tuple**; only `list` was recursed
        =========================  =========================================

        A sanitiser that silently misses a shape is worse than none, because
        the caller stops looking.
        """
        return self._redact_mapping(data)

    def _redact_mapping(self, data: dict[Any, Any]) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key, value in data.items():
            safe_key = self.redact(key) if isinstance(key, str) else key
            if safe_key in result and safe_key != key:
                # Two distinct secret keys can redact to the same marker. Losing
                # one silently would be a data-destroying sanitiser, so the
                # collision is made visible instead.
                suffix = 2
                while f"{safe_key}#{suffix}" in result:
                    suffix += 1
                safe_key = f"{safe_key}#{suffix}"
            result[safe_key] = self._redact_value(value)
        return result

    def _redact_value(self, value: Any) -> Any:
        """Redact any value, preserving its type unless a secret was found."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return self._redact_mapping(value)
        if isinstance(value, (list, tuple, set, frozenset)):
            cleaned = [self._redact_value(v) for v in value]
            return type(value)(cleaned) if not isinstance(value, list) else cleaned
        if isinstance(value, bytes):
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError:
                return value
            cleaned_text = self.redact(text)
            return cleaned_text.encode("utf-8") if cleaned_text != text else value
        # `bool` is a subclass of `int`, and checking it first keeps True/False
        # from being stringified and compared for no reason.
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            as_text = str(value)
            cleaned_text = self.redact(as_text)
            # The type is preserved unless a secret was actually found — an int
            # that happens to be a valid PAN becomes a marker, and every other
            # number stays a number.
            return cleaned_text if cleaned_text != as_text else value
        return value
