r"""FSPermissionChecker — checks filesystem operations against permission rules.

First-match-wins semantics: the first rule matching (operation, path)
determines the result. If no rule matches, the operation is allowed — these
are opt-in restrictions layered on top of the tool layer's own workspace
containment, not a standalone allowlist.

Pure service: no imports from Infrastructure.

**Normalization is the load-bearing part.** A glob compared against a raw,
caller-supplied string is trivially evaded: with a rule denying
``secrets/**``, the path ``./secrets/key`` or ``secrets//key`` or (on
Windows) ``secrets\key`` all fail to match while resolving to the denied
file. Both sides are therefore reduced to one canonical form before any
comparison. Candidate paths are additionally resolved against the workspace
root so a relative rule means what it appears to mean.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from weebot.domain.models.fs_permission import (
    FilesystemOperation,
    FilesystemPermission,
    PermissionMode,
    is_absolute_pattern,
)

logger = logging.getLogger(__name__)

try:
    import wcmatch.glob as wcglob

    _WCMATCH_AVAILABLE = True
except ImportError:
    _WCMATCH_AVAILABLE = False


def _canonical(path: str) -> str:
    """Reduce *path* to one comparable form: forward slashes, no redundancy.

    Deliberately textual (``normpath``), not ``realpath``: this must stay a
    pure service, and the tool layer has already resolved and
    workspace-confined the path by the time it gets here. Case is folded on
    Windows, where the filesystem is case-insensitive and ``Secrets/key``
    and ``secrets/key`` are the same file.
    """
    normalized = os.path.normpath(path).replace("\\", "/")
    if os.name == "nt":
        normalized = normalized.lower()
    return normalized


class FSPermissionChecker:
    """Checks file operations against a set of permission rules.

    Args:
        rules: Ordered list of FilesystemPermission rules. First match wins.
        workspace_root: Base directory that workspace-relative rule patterns
            are resolved against. Defaults to the process working directory.
    """

    def __init__(
        self, rules: list[FilesystemPermission] | None = None, workspace_root: str | None = None
    ) -> None:
        self._rules = rules or []
        self._workspace = _canonical(str(Path(workspace_root or os.getcwd())))

    @property
    def has_rules(self) -> bool:
        """True if any rule is configured. Lets callers skip the work entirely."""
        return bool(self._rules)

    def check(self, operation: FilesystemOperation, path: str) -> PermissionMode:
        """Check if *operation* on *path* is allowed.

        Returns:
            "allow", "deny", or "interrupt". Default "allow".
        """
        if not self._rules:
            return "allow"
        candidate = _canonical(path)
        for rule in self._rules:
            if operation not in rule.operations:
                continue
            if self._path_matches(candidate, rule.paths):
                return rule.mode
        return "allow"

    def filter_paths(self, operation: FilesystemOperation, paths: list[str]) -> list[str]:
        """Filter *paths*, removing those a rule denies or gates.

        Interrupt-mode paths are removed too. Listing a path is itself a
        disclosure, and this method has no way to ask anyone for approval —
        so the fail-closed reading is the only safe one here.
        """
        if not self._rules:
            return paths
        return [p for p in paths if self.check(operation, p) == "allow"]

    def _path_matches(self, candidate: str, patterns: list[str]) -> bool:
        """Check if the canonical *candidate* matches any glob in *patterns*."""
        for pattern in patterns:
            normalized = _canonical(pattern)
            if not is_absolute_pattern(pattern):
                normalized = f"{self._workspace}/{normalized}"
            if self._glob_match(candidate, normalized):
                return True
            # A rule naming a directory covers everything beneath it. Without
            # this, "secrets" would deny the directory itself but nothing in
            # it, which reads as protection while providing none.
            if not normalized.endswith("*") and self._glob_match(
                candidate, f"{normalized.rstrip('/')}/**"
            ):
                return True
            # ...and the converse: "secrets/**" must also cover the directory
            # itself, since listing it discloses the names inside.
            if normalized.endswith("/**") and candidate == normalized[:-3]:
                return True
        return False

    @staticmethod
    def _glob_match(candidate: str, pattern: str) -> bool:
        if _WCMATCH_AVAILABLE:
            flags = wcglob.BRACE | wcglob.GLOBSTAR
            return bool(wcglob.globmatch(candidate, pattern, flags=flags))
        import fnmatch

        return fnmatch.fnmatch(candidate, pattern)
