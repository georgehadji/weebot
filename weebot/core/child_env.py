"""Environment for child processes: an allowlist, never a copy of the parent environment (H1).

Merging the whole parent environment hands every provider key to every MCP server and sandbox child.
``build_child_env`` is a pure function over a ``source`` mapping, so it is tested without
touching the real environment and never returns ``None`` (an empty dict passed as ``env=``
to a subprocess call means "inherit nothing"; ``None`` means "inherit everything").
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping

BASE_POSIX = frozenset(
    {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "USER", "SHELL", "TZ"}
)
BASE_WINDOWS = frozenset(
    {
        "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP",
        "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
        "PROGRAMFILES", "PROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
        "OS",
    }
)
PROXY = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"})


def build_child_env(
    source: Mapping[str, str],
    *,
    declared: Mapping[str, str] | None = None,
    passthrough: Iterable[str] = (),
    inherit_proxy: bool = True,
    platform: str = sys.platform,
) -> dict[str, str]:
    """The allowlisted slice of *source*, overlaid with *declared* (declared values win).

    Names match case-insensitively on win32 (``Path`` vs ``PATH``) and by the proxy names
    in either case on POSIX. A declared name replaces the inherited one regardless of case.
    """
    windows = platform == "win32"
    allowed = set(BASE_WINDOWS if windows else BASE_POSIX) | set(passthrough)
    if inherit_proxy:
        allowed |= PROXY | {n.lower() for n in PROXY}
    if windows:
        allowed = {n.upper() for n in allowed}

    env: dict[str, str] = {}
    for name, value in source.items():
        if (name.upper() if windows else name) in allowed:
            env[name] = value

    for name, value in (declared or {}).items():
        if windows:
            for existing in [k for k in env if k.upper() == name.upper()]:
                del env[existing]
        env[name] = value
    return env
