"""Tests for filesystem permission rules and their enforcement (audit 5.3).

FSPermissionChecker had zero callers: a domain model, a service, and a glob
matcher, none of which any file operation consulted. Worse, its path
invariant required every pattern to start with "/", so on Windows -- where
real paths are drive-rooted -- no usable rule could even be constructed.

These tests cover the three things that make it real: patterns that work on
both platforms, normalization a caller cannot trivially evade, and an actual
call site that refuses the operation.
"""

from __future__ import annotations

import pytest

from weebot.application.services.fs_permission_checker import FSPermissionChecker
from weebot.config.fs_permissions import load_rules, parse_rules
from weebot.infrastructure.security.security_validators import PathValidator
from weebot.domain.models.fs_permission import FilesystemPermission, is_absolute_pattern

WS = "/ws"


def _checker(*rules, workspace_root=WS):
    return FSPermissionChecker(rules=list(rules), workspace_root=workspace_root)


def _deny_read(*paths):
    return FilesystemPermission(operations=["read"], paths=list(paths), mode="deny")


class TestPatternValidation:
    def test_relative_pattern_is_accepted(self):
        """The old invariant rejected this outright."""
        FilesystemPermission(operations=["read"], paths=["confidential/**"])

    def test_windows_drive_pattern_is_accepted(self):
        FilesystemPermission(operations=["read"], paths=["C:/keys/**"])

    def test_traversal_is_still_rejected(self):
        with pytest.raises(ValueError, match=r"\.\."):
            FilesystemPermission(operations=["read"], paths=["../escape"])

    def test_empty_path_is_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            FilesystemPermission(operations=["read"], paths=["   "])

    @pytest.mark.parametrize(
        "pattern,expected",
        [
            ("/etc/**", True),
            ("C:/keys", True),
            ("C:\\keys", True),
            ("confidential/**", False),
            ("*.pem", False),
        ],
    )
    def test_rootedness_detection(self, pattern, expected):
        assert is_absolute_pattern(pattern) is expected


class TestMatching:
    def test_relative_rule_resolves_against_workspace(self):
        c = _checker(_deny_read("confidential/**"))
        assert c.check("read", f"{WS}/confidential/a.txt") == "deny"

    def test_unrelated_path_is_allowed(self):
        c = _checker(_deny_read("confidential/**"))
        assert c.check("read", f"{WS}/public/a.txt") == "allow"

    def test_prefix_collision_is_not_a_match(self):
        """A confidential rule must not catch a confidentialish path."""
        c = _checker(_deny_read("confidential/**"))
        assert c.check("read", f"{WS}/confidentialish/a.txt") == "allow"

    @pytest.mark.parametrize(
        "evasion",
        ["/ws/./confidential/a.txt", "/ws/confidential//a.txt", "/ws/sub/../confidential/a.txt"],
    )
    def test_normalization_defeats_evasion(self, evasion):
        """Raw string globbing would let every one of these through."""
        c = _checker(_deny_read("confidential/**"))
        assert c.check("read", evasion) == "deny"

    def test_directory_itself_is_covered_by_a_star_rule(self):
        """Listing the directory discloses the names inside it."""
        c = _checker(_deny_read("confidential/**"))
        assert c.check("read", f"{WS}/confidential") == "deny"

    def test_bare_directory_rule_covers_contents(self):
        """Otherwise the rule reads as protection while providing none."""
        c = _checker(_deny_read("confidential"))
        assert c.check("read", f"{WS}/confidential/a.txt") == "deny"

    def test_other_operations_are_unaffected(self):
        c = _checker(_deny_read("confidential/**"))
        assert c.check("write", f"{WS}/confidential/a.txt") == "allow"

    def test_first_match_wins(self):
        c = _checker(
            FilesystemPermission(operations=["read"], paths=["logs/**"], mode="allow"),
            _deny_read("logs/**"),
        )
        assert c.check("read", f"{WS}/logs/a.txt") == "allow"

    def test_no_rules_allows_everything(self):
        c = _checker()
        assert c.has_rules is False
        assert c.check("read", "/anywhere/at/all") == "allow"


class TestFilterPaths:
    def test_denied_paths_are_removed(self):
        c = _checker(_deny_read("confidential/**"))
        kept = c.filter_paths("read", [f"{WS}/public/a", f"{WS}/confidential/b"])
        assert kept == [f"{WS}/public/a"]

    def test_interrupt_paths_are_removed_too(self):
        """filter_paths cannot ask anyone for approval, so it fails closed."""
        c = _checker(
            FilesystemPermission(operations=["read"], paths=["gated/**"], mode="interrupt")
        )
        assert c.filter_paths("read", [f"{WS}/gated/a"]) == []


class TestRulesLoader:
    def test_missing_file_yields_no_rules(self, tmp_path):
        assert load_rules(tmp_path / "nope.yaml") == []

    def test_valid_rule_parses(self):
        rules = parse_rules(
            [{"operations": ["read"], "paths": ["confidential/**"], "mode": "deny"}]
        )
        assert len(rules) == 1
        assert rules[0].mode == "deny"

    @pytest.mark.parametrize(
        "bad",
        [
            {"operations": ["bogus"], "paths": ["x"], "mode": "deny"},
            {"operations": ["read"], "paths": ["../escape"], "mode": "deny"},
            {"operations": [], "paths": ["x"], "mode": "deny"},
            {"operations": ["read"], "paths": [], "mode": "deny"},
            {"operations": ["read"], "paths": ["x"], "mode": "nonsense"},
            "not a mapping",
        ],
    )
    def test_malformed_rules_are_skipped_not_raised(self, bad):
        """A typo in an optional policy file must not be an outage."""
        assert parse_rules([bad]) == []

    def test_good_rules_survive_a_bad_neighbour(self):
        rules = parse_rules(
            [
                {"operations": ["bogus"], "paths": ["x"], "mode": "deny"},
                {"operations": ["read"], "paths": ["ok/**"], "mode": "deny"},
            ]
        )
        assert len(rules) == 1

    def test_non_list_input_is_safe(self):
        assert parse_rules(None) == []
        assert parse_rules({"not": "a list"}) == []


class TestEnforcementInFileEditor:
    """The part that was missing entirely: a caller that acts on the verdict."""

    @pytest.fixture
    def tool(self, tmp_path, monkeypatch):
        from weebot.tools import file_editor as fe

        (tmp_path / "confidential").mkdir()
        (tmp_path / "confidential" / "secret.txt").write_text("classified")
        (tmp_path / "public.txt").write_text("fine")

        monkeypatch.setattr(fe, "WORKSPACE_ROOT", str(tmp_path))
        tool = fe.StrReplaceEditorTool()
        # PathValidator captures WORKSPACE_ROOT at construction, so it needs
        # the override explicitly -- otherwise every path under tmp_path is
        # rejected by workspace containment before the policy check runs, and
        # a "deny" assertion passes for entirely the wrong reason.
        tool._workspace = tmp_path.resolve()
        tool._path_validator = PathValidator(workspace_root=tmp_path.resolve())
        return tool

    def _install(self, tool, monkeypatch, mode="deny"):
        checker = FSPermissionChecker(
            rules=[
                FilesystemPermission(
                    operations=["read", "write"], paths=["confidential/**"], mode=mode
                )
            ],
            workspace_root=str(tool._workspace),
        )
        monkeypatch.setattr(type(tool), "_fs_permissions", staticmethod(lambda: checker))

    async def test_denied_read_is_refused(self, tool, monkeypatch):
        self._install(tool, monkeypatch)
        result = await tool.execute(
            command="view", path=str(tool._workspace / "confidential" / "secret.txt")
        )
        assert result.error
        assert "filesystem policy" in result.error.lower()
        assert "classified" not in (result.output or "")

    async def test_denied_write_is_refused(self, tool, monkeypatch):
        self._install(tool, monkeypatch)
        result = await tool.execute(
            command="create", path=str(tool._workspace / "confidential" / "new.txt"), file_text="x"
        )
        assert "filesystem policy" in result.error.lower()
        assert not (tool._workspace / "confidential" / "new.txt").exists()

    async def test_interrupt_fails_closed(self, tool, monkeypatch):
        """No approval channel here, so a gate must not read as permission."""
        self._install(tool, monkeypatch, mode="interrupt")
        result = await tool.execute(
            command="view", path=str(tool._workspace / "confidential" / "secret.txt")
        )
        assert result.error
        assert "approval" in result.error.lower()

    async def test_allowed_path_still_works(self, tool, monkeypatch):
        self._install(tool, monkeypatch)
        result = await tool.execute(command="view", path=str(tool._workspace / "public.txt"))
        assert not result.error
        assert "fine" in result.output

    async def test_no_rules_means_no_behaviour_change(self, tool, monkeypatch):
        monkeypatch.setattr(
            type(tool), "_fs_permissions", staticmethod(lambda: FSPermissionChecker())
        )
        result = await tool.execute(
            command="view", path=str(tool._workspace / "confidential" / "secret.txt")
        )
        assert not result.error
        assert "classified" in result.output
