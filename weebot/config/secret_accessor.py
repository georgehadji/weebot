"""Centralised accessor for environment secrets and configuration values.

All bare ``os.environ.get()`` / ``os.getenv()`` calls throughout the
codebase MUST eventually route through this module.  This provides a
single point for auditing, logging, caching, and redacting secrets.

Usage:
    from weebot.config.secret_accessor import SecretAccessor

    api_key = SecretAccessor.get("OPENROUTER_API_KEY")
    timeout = SecretAccessor.get_int("BASH_TIMEOUT", default=120)

Singleton-like design — all members are class methods so importers never
need an instance.  The underlying source is ``os.environ``, but in the
future this could check a vault, a keyring, or a secrets manager.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── Redaction patterns for known secrets ──────────────────────────────
_SECRET_SUFFIXES = (
    "API_KEY", "API_SECRET", "SECRET", "TOKEN", "PASSWORD",
    "PRIVATE_KEY", "ACCESS_KEY", "SECRET_KEY",
)
_REDACTED = "<REDACTED>"


class SecretAccessor:
    """Centralised, auditable access to environment secrets and config.

    Class-level methods so no instance is needed.  Override the ``_source``
    in tests by calling ``SecretAccessor.set_source({"KEY": "val"})``.
    """

    _source: dict[str, str] | None = None  # None → use os.environ

    # ------------------------------------------------------------------
    # Source management (swap in tests)
    # ------------------------------------------------------------------

    @classmethod
    def set_source(cls, source: dict[str, str] | None) -> None:
        """Override the environment source (e.g. with a test dict).

        Pass ``None`` to revert to ``os.environ``.
        """
        cls._source = source

    @classmethod
    def _get_source(cls) -> dict[str, str]:
        if cls._source is not None:
            return cls._source
        return dict(os.environ)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        """Return the value for *key*, or *default* if not set.

        Logs a DEBUG message for every read for auditability.
        """
        value = cls._get_source().get(key, default)
        cls._log_access(key, value)
        return value

    @classmethod
    def get_int(cls, key: str, default: int = 0) -> int:
        """Return the value for *key* parsed as an integer."""
        raw = cls.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            logger.warning("SecretAccessor: %s is not a valid int, using default %d", key, default)
            return default

    @classmethod
    def get_bool(cls, key: str, default: bool = False) -> bool:
        """Return the value for *key* parsed as a boolean.

        Truthy values: ``"1"``, ``"true"``, ``"yes"``  (case-insensitive).
        """
        raw = cls.get(key)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes")

    @classmethod
    def get_float(cls, key: str, default: float = 0.0) -> float:
        """Return the value for *key* parsed as a float."""
        raw = cls.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except (ValueError, TypeError):
            logger.warning("SecretAccessor: %s is not a valid float, using default %f", key, default)
            return default

    @classmethod
    def require(cls, key: str) -> str:
        """Return the value for *key*, raising ``ValueError`` if missing."""
        value = cls.get(key)
        if value is None:
            raise ValueError(
                f"Required environment variable {key!r} is not set. "
                f"Check your .env file."
            )
        return value

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _log_access(cls, key: str, value: str | None) -> None:
        """Log access to *key*, redacting its value if it looks like a secret."""
        if value is None:
            logger.debug("SecretAccessor: %s = <NOT SET>", key)
        elif key.upper().endswith(_SECRET_SUFFIXES) or "SECRET" in key.upper():
            logger.debug("SecretAccessor: %s = %s (len=%d)", key, _REDACTED, len(value))
        else:
            logger.debug("SecretAccessor: %s = %r", key, value)
