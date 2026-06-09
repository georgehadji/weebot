"""FSPermissionChecker — checks filesystem operations against permission rules.

First-match-wins semantics: the first rule matching (operation, path) determines
the result. If no rule matches, the operation is allowed.

Pure service: no imports from Infrastructure.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.domain.models.fs_permission import (
    FilesystemOperation,
    FilesystemPermission,
    PermissionMode,
)

logger = logging.getLogger(__name__)

try:
    import wcmatch.glob as wcglob
    _WCMATCH_AVAILABLE = True
except ImportError:
    _WCMATCH_AVAILABLE = False


class FSPermissionChecker:
    """Checks file operations against a set of permission rules.

    Args:
        rules: Ordered list of FilesystemPermission rules. First match wins.
    """

    def __init__(self, rules: Optional[list[FilesystemPermission]] = None) -> None:
        self._rules = rules or []

    def check(
        self,
        operation: FilesystemOperation,
        path: str,
    ) -> PermissionMode:
        """Check if *operation* on *path* is allowed.

        Returns:
            "allow", "deny", or "interrupt". Default "allow".
        """
        for rule in self._rules:
            if operation not in rule.operations:
                continue
            if self._path_matches(path, rule.paths):
                return rule.mode
        return "allow"

    def filter_paths(
        self,
        operation: FilesystemOperation,
        paths: list[str],
    ) -> list[str]:
        """Filter *paths*, removing only those denied by a rule.

        Interrupt-mode paths pass through: the interrupt fires at the HITL
        stage before the tool runs, so by the time filtering runs the user
        has already approved.
        """
        if not self._rules:
            return paths
        return [
            p for p in paths
            if self.check(operation, p) != "deny"
        ]

    def _path_matches(self, path: str, patterns: list[str]) -> bool:
        """Check if *path* matches any of the glob *patterns*."""
        for pattern in patterns:
            if _WCMATCH_AVAILABLE:
                flags = wcglob.BRACE | wcglob.GLOBSTAR
                if wcglob.globmatch(path, pattern, flags=flags):
                    return True
            else:
                # Fallback: simple fnmatch-style matching
                import fnmatch
                if fnmatch.fnmatch(path, pattern):
                    return True
        return False
