"""D55 — an unreadable filesystem policy must not read as "no policy".

`FSPermissionChecker` allows by default on purpose: its docstring says the rules
are "opt-in restrictions layered on top of the tool layer's own workspace
containment, not a standalone allowlist". That is right when there is no policy.

It is wrong when there *is* a policy the loader could not read. `load_rules`
returned `[]` for both cases, and `file_editor.execute` skips the whole gate on
`if _perm.has_rules:` -- so a deny policy with one bad indent means every read
and write is allowed, with a WARNING as the only trace.

The same file already states the correct principle for the other half of the
gate: `PermissionMode` says a caller with no approval path "MUST fail closed",
and file_editor's `interrupt` branch reasons explicitly that "treating an
unanswered gate as permission would invert the rule's intent". A policy that
cannot be loaded is exactly an unanswered gate.

Violated property: **a filesystem policy that exists is enforced, or the
operation is refused.** Never silently neither.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weebot.config import fs_permissions
from weebot.config.settings import WORKSPACE_ROOT


def _abs(rel: str) -> str:
    """file_editor passes an absolute, already-resolved path; so do we.

    `FSPermissionChecker` resolves workspace-relative *patterns* against the
    workspace root but not *candidates*, so a relative candidate silently
    matches nothing. See D56.
    """
    return str(Path(WORKSPACE_ROOT) / rel)

_VALID = (
    "version: 1\n"
    "rules:\n"
    '  - operations: [read, write]\n'
    '    paths: ["confidential/**"]\n'
    "    mode: deny\n"
)
# One space missing before `paths` — the whole document fails to parse.
_BAD_INDENT = (
    "version: 1\n"
    "rules:\n"
    '  - operations: [read, write]\n'
    '   paths: ["confidential/**"]\n'
    "    mode: deny\n"
)


def _checker_for(body: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build the process checker from *body*, or from no file when None."""
    path = tmp_path / "fs_permissions.yaml"
    if body is not None:
        path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(fs_permissions, "_RULES_PATH", path)
    fs_permissions.load_fs_permission_checker.cache_clear()
    return fs_permissions.load_fs_permission_checker()


def test_absent_policy_still_allows_everything(tmp_path, monkeypatch) -> None:
    """The default install ships no policy file. That must not change."""
    checker = _checker_for(None, tmp_path, monkeypatch)
    assert checker.has_rules is False
    assert checker.check("write", _abs("anything.txt")) == "allow"


def test_a_valid_policy_is_enforced(tmp_path, monkeypatch) -> None:
    checker = _checker_for(_VALID, tmp_path, monkeypatch)
    assert checker.has_rules is True
    assert checker.check("read", _abs("confidential/keys.txt")) == "deny"
    assert checker.check("write", _abs("ordinary.txt")) == "allow"


def test_a_policy_that_will_not_parse_fails_closed(tmp_path, monkeypatch) -> None:
    """One bad indent must not silently disable the whole policy."""
    checker = _checker_for(_BAD_INDENT, tmp_path, monkeypatch)
    assert checker.has_rules is True, "the gate is skipped entirely when has_rules is False"
    assert checker.check("read", _abs("confidential/keys.txt")) == "deny"
    assert checker.check("write", _abs("ordinary.txt")) == "deny"


@pytest.mark.parametrize(
    "body",
    [
        "- operations: [read]\n  paths: ['x/**']\n  mode: deny\n",  # a bare list
        "just a string\n",  # a bare scalar
        "12345\n",
    ],
)
def test_valid_yaml_that_is_not_a_mapping_fails_closed(body, tmp_path, monkeypatch) -> None:
    """`data.get("rules")` sat outside the try, so these raised AttributeError
    out of the loader and up through the tool call."""
    checker = _checker_for(body, tmp_path, monkeypatch)
    assert checker.check("write", _abs("ordinary.txt")) == "deny"


def test_an_unreadable_policy_is_reported_at_error(tmp_path, monkeypatch, caplog) -> None:
    """Losing a filesystem policy is not a warning-level event."""
    with caplog.at_level("ERROR", logger="weebot.config.fs_permissions"):
        _checker_for(_BAD_INDENT, tmp_path, monkeypatch)
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_a_rule_level_typo_still_only_drops_that_rule(tmp_path, monkeypatch) -> None:
    """The per-rule tolerance is correct and must survive: a rule that fails to
    parse never enforced anything. Only a whole-file failure is fail-closed."""
    body = (
        "version: 1\n"
        "rules:\n"
        '  - operations: [nonsense]\n'
        '    paths: ["x/**"]\n'
        "    mode: deny\n"
        '  - operations: [read]\n'
        '    paths: ["confidential/**"]\n'
        "    mode: deny\n"
    )
    checker = _checker_for(body, tmp_path, monkeypatch)
    assert checker.check("read", _abs("confidential/k.txt")) == "deny"
    assert checker.check("read", _abs("ordinary.txt")) == "allow"


def test_a_zero_byte_policy_file_fails_closed(tmp_path, monkeypatch) -> None:
    """An empty file is what a truncated write leaves behind, and "no rules" is
    already expressible by having no file at all."""
    checker = _checker_for("", tmp_path, monkeypatch)
    assert checker.check("write", _abs("ordinary.txt")) == "deny"


def test_an_explicit_empty_rule_list_is_respected(tmp_path, monkeypatch) -> None:
    """`rules: []` is a deliberate statement, unlike a file that says nothing."""
    checker = _checker_for("version: 1\nrules: []\n", tmp_path, monkeypatch)
    assert checker.has_rules is False
    assert checker.check("write", _abs("ordinary.txt")) == "allow"
