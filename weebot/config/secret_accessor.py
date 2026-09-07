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

logger = logging.getLogger(__name__)

# ── Redaction helpders ───────────────────────────────────────────────

# Keys whose values are logged in plaintext (non-secret config).
_NON_SECRET_SUFFIXES = (
    "DIR",
    "URL",
    "HOST",
    "PORT",
    "MODE",
    "TIMEOUT",
    "_DIR",
    "_URL",
    "_HOST",
    "_PORT",
    "_MODE",
    "_TIMEOUT",
)
_NON_SECRET_KEYS: set[str] = {
    "WEEBOT_WORKSPACE",
    "WEEBOT_LOGS_DIR",
    "WEEBOT_SESSIONS_DB",
    "WEEBOT_HOST",
    "WEEBOT_PORT",
    "WEEBOT_CORS_ORIGIN",
    "SANDBOX_MODE",
    "BASH_TIMEOUT",
    "PYTHON_TIMEOUT",
    "SANDBOX_MAX_OUTPUT_BYTES",
    "SANDBOX_ALLOW_NETWORK",
    "DAILY_AI_BUDGET",
    "WEEBOT_WEB_REQUIRE_AUTH",
}
_REDACTED = "<REDACTED>"


def _sanitize_non_secret(value: str) -> str:
    """Scrub credentials out of a value the name-based allowlist waved through.

    `_is_non_secret` is a deny-by-shape heuristic ("a name ending in URL is
    config") used as an ALLOW rule ("so log the whole thing"). Names are not
    evidence about values, and URLs are where credentials live. Measured, at
    DEBUG, before this existed:

        DATABASE_URL      = 'postgres://admin:hunter2@db.internal:5432/prod'
        REDIS_URL         = 'rediss://:s3cr3tpassword@cache.internal:6379/0'
        SLACK_WEBHOOK_URL = 'https://hooks.slack.com/services/T00/B00/XXXX…'

    All three are the credential itself, and a Slack webhook URL has no
    non-secret part at all.

    The allowlist is left alone rather than argued with: the point of logging
    a `*_URL` plainly is to see the host you are talking to, and that survives.
    Only the credential inside it does not.
    """
    try:
        from weebot.core.credential_sanitizer import sanitize

        return sanitize(value)
    except Exception:
        # Never let the log path raise. Falling back to the redaction marker is
        # the safe direction: worse diagnostics, no leak.
        logger.debug("Sanitising a non-secret value failed.", exc_info=True)
        return _REDACTED


def _is_non_secret(key: str) -> bool:
    """Return True if *key* is considered non-secret for logging."""
    if key in _NON_SECRET_KEYS:
        return True
    upper = key.upper()
    for suffix in _NON_SECRET_SUFFIXES:
        if upper.endswith(suffix):
            return True
    return False


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
    def get(cls, key: str, default: str | None = None) -> str | None:
        """Return the value for *key*, or *default* if not set.

        Logs a DEBUG message for every read for auditability.
        """
        value = cls._get_source().get(key, default)
        cls._log_access(key, value)
        return value

    @classmethod
    def get_unredacted(cls, key: str, default: str | None = None) -> str | None:
        """Return the value for *key* without redaction in logs.

        Use sparingly — only for non-sensitive config that needs to be
        visible at debug level for troubleshooting.
        """
        value = cls._get_source().get(key, default)
        if value is not None:
            logger.debug("SecretAccessor (unredacted): %s = %r", key, value)
        else:
            logger.debug("SecretAccessor (unredacted): %s = <NOT SET>", key)
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
            logger.warning(
                "SecretAccessor: %s is not a valid float, using default %f", key, default
            )
            return default

    @classmethod
    def require(cls, key: str) -> str:
        """Return the value for *key*, raising ``ValueError`` if missing."""
        value = cls.get(key)
        if value is None:
            raise ValueError(
                f"Required environment variable {key!r} is not set. " f"Check your .env file."
            )
        return value

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _log_access(cls, key: str, value: str | None) -> None:
        """Log access to *key*, redacting its value by default.

        Values are redacted unless the key matches a small non-secret
        allowlist (see ``_is_non_secret``). The length of the value is
        always logged (non-sensitive metadata).
        """
        if value is None:
            logger.debug("SecretAccessor: %s = <NOT SET>", key)
        elif _is_non_secret(key):
            logger.debug("SecretAccessor: %s = %r", key, _sanitize_non_secret(value))
        else:
            logger.debug("SecretAccessor: %s = %s (len=%d)", key, _REDACTED, len(value))
