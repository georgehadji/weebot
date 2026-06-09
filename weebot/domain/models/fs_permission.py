"""FilesystemPermission — declarative path-level access control.

Pure domain model: no imports from Application or Infrastructure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


FilesystemOperation = Literal["read", "write", "execute"]
"""Operations that can be gated by a permission rule."""


PermissionMode = Literal["allow", "deny", "interrupt"]
"""Effect when a tool call matches a permission rule:
- allow: the call proceeds (default).
- deny: the tool returns a permission-denied error.
- interrupt: the call is paused for human approval (requires HumanInTheLoopMiddleware).
"""


@dataclass(frozen=True)
class FilesystemPermission:
    """A single access rule for filesystem operations.

    Args:
        operations: Which operations this rule applies to.
        paths: Glob patterns matching file paths. Must start with '/'.
        mode: Effect when a tool call matches.
    """

    operations: list[FilesystemOperation]
    paths: list[str]
    mode: PermissionMode = "allow"

    def __post_init__(self) -> None:
        for path in self.paths:
            if not path.startswith("/"):
                raise ValueError(f"Permission path must start with '/': {path!r}")
            if ".." in path:
                raise ValueError(f"Permission path must not contain '..': {path!r}")
