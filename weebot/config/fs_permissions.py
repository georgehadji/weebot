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
from typing import Any, Optional

from weebot.application.services.fs_permission_checker import FSPermissionChecker
from weebot.domain.models.fs_permission import FilesystemPermission

logger = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).resolve().parent / "fs_permissions.yaml"

_VALID_OPERATIONS = {"read", "write", "execute"}
_VALID_MODES = {"allow", "deny", "interrupt"}


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
            logger.warning("fs_permissions rule %d has unknown operations %s; skipped", index, sorted(bad_ops))
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


def load_rules(path: Optional[Path] = None) -> list[FilesystemPermission]:
    """Read and parse the rules file. Returns [] when it does not exist."""
    rules_path = path or _RULES_PATH
    if not rules_path.exists():
        return []
    try:
        import yaml
        with rules_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("Could not read %s: %s — no filesystem rules applied", rules_path, exc)
        return []
    return parse_rules(data.get("rules"))


@lru_cache(maxsize=1)
def load_fs_permission_checker() -> FSPermissionChecker:
    """Process-wide checker built from the rules file."""
    from weebot.config.settings import WORKSPACE_ROOT

    rules = load_rules()
    if rules:
        logger.info("Loaded %d filesystem permission rule(s)", len(rules))
    return FSPermissionChecker(rules=rules, workspace_root=str(WORKSPACE_ROOT))
