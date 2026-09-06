"""Loader for filesystem permission rules.

Rules live in ``weebot/config/fs_permissions.yaml``. The file is optional and
ships absent, so the default configuration has **no rules and no behaviour
change** — the checker is a no-op until someone writes a policy.

Format::

    version: 1
    rules:
      - operations: [read]
        paths: ["confidential/**", "**/*.pem"]
        mode: deny
      - operations: [write]
        paths: ["migrations/**"]
        mode: interrupt

``paths`` are globs, either rooted ("/etc/**", "C:/keys/**") or relative to
the workspace root. ``mode`` is allow | deny | interrupt. First match wins.

Loaded once per process and cached: this is read on every gated file
operation, and re-parsing YAML per call would put disk I/O in the tool path.
Call ``load_fs_permission_checker.cache_clear()`` in tests.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from weebot.application.services.fs_permission_checker import FSPermissionChecker
from weebot.domain.models.fs_permission import FilesystemPermission

logger = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).resolve().parent / "fs_permissions.yaml"

_VALID_OPERATIONS = {"read", "write", "execute"}
_VALID_MODES = {"allow", "deny", "interrupt"}


class FSPolicyUnreadable(RuntimeError):
    """A policy file exists but could not be turned into rules.

    Distinct from "there is no policy", which is the documented default and is
    represented by an empty rule list. Collapsing the two is what let a single
    bad indent disable every rule silently.
    """


#: Installed when a policy exists but cannot be read. `FSPermissionChecker`
#: resolves a workspace-relative pattern against the workspace root, so "**"
#: covers everything inside it; "/**" covers anything rooted outside.
_DENY_EVERYTHING = [
    FilesystemPermission(
        operations=["read", "write", "execute"], paths=["**", "/**"], mode="deny"
    )
]


def parse_rules(raw: Any) -> list[FilesystemPermission]:
    """Parse the ``rules:`` block into domain objects, skipping bad entries.

    A malformed rule is dropped with a warning rather than raising. The
    alternative — refusing to start — turns a typo in an optional policy file
    into an outage. Dropping is safe here because a rule that fails to parse
    was never enforcing anything.
    """
    if not isinstance(raw, list):
        return []
    rules: list[FilesystemPermission] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            logger.warning("fs_permissions rule %d is not a mapping; skipped", index)
            continue
        operations = [str(o).lower() for o in entry.get("operations", [])]
        paths = [str(p) for p in entry.get("paths", [])]
        mode = str(entry.get("mode", "allow")).lower()

        bad_ops = set(operations) - _VALID_OPERATIONS
        if bad_ops:
            logger.warning(
                "fs_permissions rule %d has unknown operations %s; skipped", index, sorted(bad_ops)
            )
            continue
        if not operations or not paths:
            logger.warning("fs_permissions rule %d needs both operations and paths; skipped", index)
            continue
        if mode not in _VALID_MODES:
            logger.warning("fs_permissions rule %d has unknown mode %r; skipped", index, mode)
            continue
        try:
            rules.append(FilesystemPermission(operations=operations, paths=paths, mode=mode))  # type: ignore[arg-type]
        except ValueError as exc:
            logger.warning("fs_permissions rule %d rejected: %s", index, exc)
    return rules


def load_rules(path: Path | None = None) -> list[FilesystemPermission]:
    """Read and parse the rules file.

    Returns ``[]`` only when there is no policy file -- the documented default,
    where the checker is a deliberate no-op. A file that exists but cannot be
    turned into rules raises ``FSPolicyUnreadable`` instead: the operator wrote
    a policy, and answering that with "no rules" is indistinguishable from
    answering it with "no policy", which is how one bad indent used to disable
    the whole thing.
    """
    rules_path = path or _RULES_PATH
    if not rules_path.exists():
        return []
    try:
        import yaml

        with rules_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            # Valid YAML, wrong shape. `data.get("rules")` used to sit outside
            # this try, so a bare list or scalar raised AttributeError out of
            # the loader and up through whatever tool call triggered it.
            raise TypeError(f"expected a mapping at the top level, got {type(data).__name__}")
        if "rules" not in data:
            # A file with no `rules:` key at all -- including a zero-byte one,
            # which is what a truncated write leaves behind. "No rules" is
            # already expressible by having no file, so a file that says
            # nothing is a signal something went wrong, not a policy. An
            # explicit `rules: []` is respected and means exactly no rules.
            raise KeyError("no 'rules:' key")
        return parse_rules(data["rules"])
    except Exception as exc:
        raise FSPolicyUnreadable(f"{rules_path}: {exc}") from exc


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
