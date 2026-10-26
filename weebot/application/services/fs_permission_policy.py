"""Builds the process-wide ``FSPermissionChecker`` from the rules file.

``weebot.config.fs_permissions`` only loads data (rules); constructing the
application service lives here so ``weebot.config`` stays a leaf (plan 3.9).

Loaded once per process and cached: this is read on every gated file
operation, and re-parsing YAML per call would put disk I/O in the tool path.
Call ``load_fs_permission_checker.cache_clear()`` in tests.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from weebot.application.services.fs_permission_checker import FSPermissionChecker
from weebot.config.fs_permissions import FSPolicyUnreadable, load_rules
from weebot.domain.models.fs_permission import FilesystemPermission

logger = logging.getLogger(__name__)

#: Installed when a policy exists but cannot be read. `FSPermissionChecker`
#: resolves a workspace-relative pattern against the workspace root, so "**"
#: covers everything inside it; "/**" covers anything rooted outside.
_DENY_EVERYTHING = [
    FilesystemPermission(
        operations=["read", "write", "execute"], paths=["**", "/**"], mode="deny"
    )
]


@lru_cache(maxsize=1)
def load_fs_permission_checker() -> FSPermissionChecker:
    """Process-wide checker built from the rules file."""
    from weebot.config.settings import WORKSPACE_ROOT

    try:
        rules = load_rules()
    except FSPolicyUnreadable as exc:
        # Fail closed. `PermissionMode` states the rule for the other half of
        # this gate -- a caller with no approval path "MUST fail closed" -- and
        # a policy that cannot be loaded is exactly an unanswered gate. The
        # cost is real and deliberate: a typo in the policy blocks file
        # operations until it is fixed. The alternative is an operator who
        # believes they are protected and is not.
        logger.error(
            "Filesystem policy could not be loaded (%s). Denying all gated file "
            "operations until it parses. Fix the file, or remove it to restore "
            "the unrestricted default.",
            exc,
        )
        return FSPermissionChecker(
            rules=list(_DENY_EVERYTHING), workspace_root=str(WORKSPACE_ROOT)
        )
    if rules:
        logger.info("Loaded %d filesystem permission rule(s)", len(rules))
    return FSPermissionChecker(rules=rules, workspace_root=str(WORKSPACE_ROOT))
