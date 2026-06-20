"""Unit tests for output_path resolver."""
from __future__ import annotations

import pytest

from weebot.core.output_path import output_path, output_dir


class TestOutputPath:
    def test_relative_returns_absolute(self):
        result = output_path("Output/test/file.txt")
        # Normalize to forward slashes for cross-platform assertions
        norm = result.replace("\\", "/")
        assert norm.endswith("Output/test/file.txt")
        assert "weebot" in norm

    def test_already_absolute_under_project(self):
        import os
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent.parent
        abs_path = str(root / "Output" / "x.txt")
        result = output_path(abs_path)
        assert abs_path.replace("\\", "/") == result.replace("\\", "/")

    def test_backslash_normalized(self):
        result = output_path("Output\\test\\file.txt")
        # On Windows, Path() returns backslashes. The function preserves
        # the OS-native separator. The key invariant: no double separators.
        norm = result.replace("\\", "/")
        assert "Output/test/file.txt" in norm

    def test_dot_dot_traversal_blocked(self):
        with pytest.raises(ValueError, match="Path traversal"):
            output_path("Output/../outside/file.txt")

    def test_output_dir_creates_parents(self, tmp_path):
        import os
        # Override the module-level cache for testing
        import weebot.core.output_path as mod
        old_root = mod._PROJECT_ROOT
        mod._PROJECT_ROOT = tmp_path
        try:
            result = output_dir("Output/nested/deep/file.txt")
            assert os.path.isdir(tmp_path / "Output" / "nested" / "deep")
            assert result == str(tmp_path / "Output" / "nested" / "deep" / "file.txt")
        finally:
            mod._PROJECT_ROOT = old_root
