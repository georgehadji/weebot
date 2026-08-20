"""Tests for H3 (denied basenames) and H4 (create extension restrictions)."""

from weebot.infrastructure.security.security_validators import PathValidator, ValidationResult


class TestDeniedBasenames:
    """H3 — denied basename checks apply to ALL operations."""

    def test_env_file_blocked_for_view(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / ".env")
        assert report.result == ValidationResult.DANGEROUS_PATTERN

    def test_env_local_blocked(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / ".env.local")
        assert report.result == ValidationResult.DANGEROUS_PATTERN

    def test_env_example_allowed(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / ".env.example")
        assert report.result == ValidationResult.VALID

    def test_id_rsa_blocked(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / "id_rsa")
        assert report.result == ValidationResult.DANGEROUS_PATTERN


class TestCreateExtensionRestrictions:
    """H4 — executable extensions blocked for creation; editing existing allowed."""

    def test_create_ps1_blocked(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / "evil.ps1", allow_create=True)
        assert report.result == ValidationResult.DANGEROUS_PATTERN

    def test_create_sh_blocked(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / "script.sh", allow_create=True)
        assert report.result == ValidationResult.DANGEROUS_PATTERN

    def test_create_md_allowed(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / "notes.md", allow_create=True)
        assert report.result == ValidationResult.VALID

    def test_str_replace_existing_sh_allowed(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / "script.sh", allow_create=False)
        assert report.result == ValidationResult.VALID

    def test_py_allowed_for_create(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / "main.py", allow_create=True)
        assert report.result == ValidationResult.VALID

    def test_dockerfile_no_extension_allowed(self, workspace_path):
        validator = PathValidator(workspace_path)
        report = validator.validate(workspace_path / "Dockerfile", allow_create=True)
        assert report.result == ValidationResult.VALID
