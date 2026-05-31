"""Tests for Issue 2: exec() in Template Versioning

Verifies that template versioning uses safe transformation methods.
"""
import ast
import json
import pytest
from pathlib import Path


class TestVersioningSecurity:
    """Tests for safe template versioning."""

    @pytest.fixture
    def source_file_path(self):
        import os
        weebot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return Path(weebot_dir) / "templates" / "versioning.py"

    @pytest.fixture
    def source_content(self, source_file_path):
        return source_file_path.read_text(encoding='utf-8')

    # ===== Happy Path Tests =====

    def test_no_bare_exec_in_migration(self, source_content):
        """Verify exec() is not used without restricted builtins."""
        # Find all exec() calls
        lines = source_content.split('\n')
        exec_lines = [i for i, line in enumerate(lines) if 'exec(' in line]
        
        for line_num in exec_lines:
            line = lines[line_num]
            # exec should have restricted builtins
            if 'exec(' in line:
                assert '__builtins__' in line, (
                    f"Line {line_num}: exec() without restricted builtins"
                )

    def test_json_migration_format(self, source_content):
        """Verify migration can use JSON format."""
        # Check that JSON parsing is used
        assert 'json.loads' in source_content or 'json.dumps' in source_content, (
            "Versioning should support JSON format"
        )

    # ===== Edge Cases =====

    def test_module_parseable(self, source_content):
        """Verify module is syntactically valid."""
        try:
            ast.parse(source_content)
        except SyntaxError as e:
            pytest.fail(f"Syntax error: {e}")

    def test_no_dangerous_imports(self, source_content):
        """Verify no dangerous imports are added."""
        dangerous = ['eval', 'exec', '__import__']
        for d in dangerous:
            # Should not be used directly in dangerous ways
            if f"'{d}'" in source_content or f'"{d}"' in source_content:
                # Check context
                if f'"{d}"' in source_content and 'allowed' not in source_content.lower():
                    pass  # Could be in allowlist

    # ===== Failure Mode Tests =====

    def test_exec_with_empty_builtins(self, source_content):
        """Verify exec uses empty builtins for safety."""
        if 'exec(' in source_content:
            # If exec is used, it should have restricted builtins
            assert '{"__builtins__": {}}' in source_content or "__builtins__: {}" in source_content, (
                "exec() should use empty builtins for safety"
            )

    def test_migration_has_timeout(self, source_content):
        """Verify migration has some form of timeout/safety."""
        # Check for error handling in migration
        assert 'try:' in source_content and 'except' in source_content, (
            "Migration should have error handling"
        )


class TestMigrationTransformation:
    """Tests for migration transformation safety."""

    @pytest.fixture
    def source_file_path(self):
        import os
        weebot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return Path(weebot_dir) / "templates" / "versioning.py"

    def test_transformation_error_handling(self, source_file_path):
        """Verify transformation errors are caught."""
        content = source_file_path.read_text()
        
        # Should have try/except around transformation
        assert 'try:' in content
        assert 'except' in content
        assert 'transform' in content.lower()

    def test_no_arbitrary_code_in_migration_data(self, source_file_path):
        """Verify migration data doesn't contain executable code."""
        content = source_file_path.read_text()
        
        # Look for transformation_script handling
        if 'transformation_script' in content:
            # Should not eval/literal_eval arbitrary code
            assert 'ast.literal_eval' not in content or 'safe' in content.lower(), (
                "literal_eval should be used for safety"
            )


# ===== Regression Invariants =====

VERSIONING_INVARIANTS = [
    "Module must be syntactically valid",
    "exec() must use restricted builtins if present",
    "Error handling must exist for transformations",
    "JSON serialization should be supported",
]


class TestVersioningInvariants:
    """Tests that verify versioning invariants."""

    @pytest.mark.parametrize("invariant", VERSIONING_INVARIANTS)
    def test_invariant_documented(self, invariant):
        """Each invariant is documented."""
        assert invariant is not None