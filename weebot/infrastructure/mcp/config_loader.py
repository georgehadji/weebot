"""MCP config loader — env-var interpolation for MCP server configurations.

Provides a single shared `expand_env` implementation used by both the DI
factory (`_factories.py`) and the CLI (`cli/commands/mcp.py`) so that secrets
can be resolved from environment variables rather than inlined in config files.

Usage::

    from weebot.infrastructure.mcp.config_loader import expand_env

    raw = json.loads(path.read_text())
    servers = expand_env(raw)
"""
from __future__ import annotations

import os
import re
import logging
from typing import Any

_log = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when MCP configuration is invalid or incomplete.

    Examples:
        - Environment variable referenced in config is not set.
        - Config file cannot be parsed.
    """
    pass


def expand_env(obj: Any) -> Any:
    """Recursively expand ``${VAR}`` and ``$VAR`` in all string values.

    - ``os.path.expandvars`` is used for the actual substitution so we
      inherit correct platform behaviour.
    - After expansion, any remaining literal ``${...}`` or ``$VAR``
      pattern not matching an env var causes a ``ConfigError``.
    - Non-string leaves (numbers, booleans, None) pass through untouched.

    Raises:
        ConfigError: If any env variable referenced in a string value is
            not set in the environment.
    """
    if isinstance(obj, str):
        return _expand_string(obj)
    if isinstance(obj, dict):
        return {k: expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env(v) for v in obj]
    return obj


def _expand_string(s: str) -> str:
    """Expand env vars in a single string, failing closed on unset vars."""
    # First pass: use os.path.expandvars for standard substitution
    expanded = os.path.expandvars(s)

    # Second pass: detect any remaining ${VAR} or $VAR that weren't expanded.
    # os.path.expandvars leaves unset vars as-is (e.g. "${X_BEARER}" stays).
    remaining = re.findall(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)", expanded)
    for braced, simple in remaining:
        var_name = braced or simple
        if var_name and os.environ.get(var_name) is None:
            if re.search(re.escape(f"${{{var_name}}}") + r"|" + re.escape(f"${var_name}"), expanded):
                raise ConfigError(
                    f"Environment variable ${var_name} is required but not set. "
                    f"Set it in your .env file or shell before starting weebot."
                )

    return expanded
