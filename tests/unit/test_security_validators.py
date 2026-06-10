"""Unit tests for security validators — Fixes 1-4 from execution_fixes_plan."""
from __future__ import annotations

from pathlib import Path

from weebot.infrastructure.security.security_validators import (
    PathValidator,
    CommandValidator,
    ValidationResult,
)


class TestPathValidatorExtensions:

    def test_allows_env_example(self, tmp_path: Path) -> None:
        v = PathValidator(workspace_root=tmp_path)
        path = tmp_path / ".env.example"
        report = v.validate(path, allow_create=True)
        assert report.result == ValidationResult.VALID

    def test_allows_toml(self, tmp_path: Path) -> None:
        v = PathValidator(workspace_root=tmp_path)
        path = tmp_path / "pyproject.toml"
        report = v.validate(path)
        assert report.result == ValidationResult.VALID

    def test_allows_gitignore(self, tmp_path: Path) -> None:
        v = PathValidator(workspace_root=tmp_path)
        path = tmp_path / ".gitignore"
        report = v.validate(path, allow_create=True)
        assert report.result == ValidationResult.VALID

    def test_allows_dockerignore(self, tmp_path: Path) -> None:
        v = PathValidator(workspace_root=tmp_path)
        path = tmp_path / ".dockerignore"
        report = v.validate(path, allow_create=True)
        assert report.result == ValidationResult.VALID

    def test_allows_editorconfig(self, tmp_path: Path) -> None:
        v = PathValidator(workspace_root=tmp_path)
        path = tmp_path / ".editorconfig"
        report = v.validate(path, allow_create=True)
        assert report.result == ValidationResult.VALID

    def test_allows_gitkeep(self, tmp_path: Path) -> None:
        v = PathValidator(workspace_root=tmp_path)
        path = tmp_path / ".gitkeep"
        report = v.validate(path, allow_create=True)
        assert report.result == ValidationResult.VALID

    def test_allows_lock(self, tmp_path: Path) -> None:
        v = PathValidator(workspace_root=tmp_path)
        path = tmp_path / "Cargo.lock"
        report = v.validate(path)
        assert report.result == ValidationResult.VALID

    def test_allows_pyi(self, tmp_path: Path) -> None:
        v = PathValidator(workspace_root=tmp_path)
        path = tmp_path / "stubs.pyi"
        report = v.validate(path)
        assert report.result == ValidationResult.VALID


class TestCommandValidatorPythonImports:

    def test_sys_import_raises_confirmation(self) -> None:
        v = CommandValidator()
        report = v.validate_python("import sys\nprint(sys.argv)")
        assert report.result == ValidationResult.DANGEROUS_PATTERN
        assert "confirmation" in report.message.lower()
        assert "sys" in report.message

    def test_ctypes_import_is_blocked(self) -> None:
        v = CommandValidator()
        report = v.validate_python("import ctypes")
        assert report.result == ValidationResult.DANGEROUS_PATTERN
        assert "not allowed" in report.message.lower()

    def test_mmap_import_is_blocked(self) -> None:
        v = CommandValidator()
        report = v.validate_python("import mmap")
        assert report.result == ValidationResult.DANGEROUS_PATTERN
        assert "not allowed" in report.message.lower()

    def test_builtins_import_is_blocked(self) -> None:
        v = CommandValidator()
        report = v.validate_python("import builtins")
        assert report.result == ValidationResult.DANGEROUS_PATTERN
        assert "not allowed" in report.message.lower()

    def test_socket_import_raises_confirmation(self) -> None:
        v = CommandValidator()
        report = v.validate_python("import socket")
        assert report.result == ValidationResult.DANGEROUS_PATTERN
        assert "confirmation" in report.message.lower()
        assert "socket" in report.message

    def test_harmless_import_passes(self) -> None:
        v = CommandValidator()
        report = v.validate_python("import os\nimport pathlib\nimport json")
        assert report.result == ValidationResult.VALID

    def test_from_syntax_blocked_import(self) -> None:
        v = CommandValidator()
        report = v.validate_python("from ctypes import windll")
        assert report.result == ValidationResult.DANGEROUS_PATTERN
        assert "not allowed" in report.message.lower()

    def test_from_syntax_confirmation_import(self) -> None:
        v = CommandValidator()
        report = v.validate_python("from sys import argv")
        assert report.result == ValidationResult.DANGEROUS_PATTERN
        assert "confirmation" in report.message.lower()


class TestCommandValidatorPowerShell:

    def test_execution_policy_bypass_blocked(self) -> None:
        v = CommandValidator()
        r = v.validate_powershell("powershell -ExecutionPolicy Bypass -File script.ps1")
        assert r.result == ValidationResult.DANGEROUS_PATTERN

    def test_ep_bypass_blocked(self) -> None:
        v = CommandValidator()
        r = v.validate_powershell('powershell -ep bypass -Command "Get-Process"')
        assert r.result == ValidationResult.DANGEROUS_PATTERN

    def test_bypass_in_variable_name_not_blocked(self) -> None:
        v = CommandValidator()
        r = v.validate_powershell("$bypass_check = $false; Write-Output 'done'")
        assert r.result == ValidationResult.VALID

    def test_bypass_in_comment_not_blocked(self) -> None:
        v = CommandValidator()
        r = v.validate_powershell("# bypass the check\nWrite-Output 'hello'")
        assert r.result == ValidationResult.VALID


class TestCommandValidatorBashPowerShellSeparation:

    def test_powershell_subexpression_not_flagged(self) -> None:
        v = CommandValidator()
        r = v.validate_bash('Get-ChildItem | Where-Object {$_.Length -gt $($limit * 2)}')
        assert r.result == ValidationResult.VALID

    def test_bash_command_substitution_still_blocked(self) -> None:
        v = CommandValidator()
        r = v.validate_bash('echo $(cat /etc/passwd)')
        assert r.result == ValidationResult.DANGEROUS_PATTERN

    def test_short_substitution_not_blocked(self) -> None:
        v = CommandValidator()
        r = v.validate_bash('echo $()')
        assert r.result == ValidationResult.VALID

    def test_powershell_without_cmdlet_indicators_is_bash_substitution(self) -> None:
        """$(expr) without PowerShell cmdlet indicators is treated as bash substitution."""
        v = CommandValidator()
        r = v.validate_bash('$(1 + 2)')
        # This is bash $() substitution with 3+ chars content — correctly blocked
        assert r.result == ValidationResult.DANGEROUS_PATTERN
