"""Unit tests for security validators — Fixes 1-4 from execution_fixes_plan."""

from __future__ import annotations

from pathlib import Path

from weebot.infrastructure.security.security_validators import (
    PathValidator,
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


