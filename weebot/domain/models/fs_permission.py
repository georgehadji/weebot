"""FilesystemPermission — declarative path-level access control.

Pure domain model: no imports from Application or Infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FilesystemOperation = Literal["read", "write", "execute"]
"""Operations that can be gated by a permission rule."""


PermissionMode = Literal["allow", "deny", "interrupt"]
"""Effect when a tool call matches a permission rule:
- allow: the call proceeds (default).
- deny: the tool returns a permission-denied error.
- interrupt: the call requires explicit human approval. Callers with no
  approval path of their own MUST fail closed and treat it as deny.
"""


def is_absolute_pattern(pattern: str) -> bool:
    """True if *pattern* is rooted rather than workspace-relative.

    Recognises POSIX roots and Windows drive roots. A pattern that is
    neither is interpreted relative to the workspace root by
    FSPermissionChecker.
    """
    if pattern.startswith("/") or pattern.startswith("\\"):
        return True
    return len(pattern) >= 3 and pattern[1] == ":" and pattern[2] in ("/", "\\")


@dataclass(frozen=True)
class FilesystemPermission:
    """A single access rule for filesystem operations.

    Args:
        operations: Which operations this rule applies to.
        paths: Glob patterns matching file paths. Either rooted (POSIX
            "/etc/**" or Windows "C:/keys/**") or workspace-relative
            ("confidential/**").
        mode: Effect when a tool call matches.

    The original invariant required every pattern to start with "/". That
    made the mechanism unusable on Windows, where real paths are drive
    rooted, and blocked the natural way to state a project policy
    ("confidential/**"). Rooted-ness is a matching detail, not a validation
    rule -- see is_absolute_pattern.

    The ".." ban is kept and is load-bearing: it stops a rule being written
    so that it silently resolves outside the subtree it appears to name.
    """

    operations: list[FilesystemOperation]
    paths: list[str]
    mode: PermissionMode = "allow"

    def __post_init__(self) -> None:
        for path in self.paths:
            if not path or not path.strip():
                raise ValueError("Permission path must not be empty")
            if ".." in path:
                raise ValueError(f"Permission path must not contain '..': {path!r}")
