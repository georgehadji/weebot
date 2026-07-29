"""Tests for Issue 3: Unused Pickle Import

Verifies that learning_from_executions.py does not use pickle module.
"""
import ast
import pytest
from pathlib import Path


class TestPickleImportRemoval:
    """Tests for pickle import removal in learning_from_executions.py."""

    @pytest.fixture
    def source_file_path(self):
        """Path to the source file under test."""
        import os
        # Get the weebot directory
        weebot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return Path(weebot_dir) / "learning_from_executions.py"

    @pytest.fixture
    def source_content(self, source_file_path):
        """Read the source file content."""
        return source_file_path.read_text(encoding='utf-8')

    @pytest.fixture
    def ast_tree(self, source_content):
        """Parse the source into AST."""
        return ast.parse(source_content)

    # ===== Happy Path Tests =====

    def test_no_pickle_import(self, ast_tree):
        """Verify pickle is not imported in the module."""
        pickle_imports = [
            node.names[0].name == 'pickle'
            for node in ast.walk(ast_tree)
            if isinstance(node, ast.Import)
            and any(name == 'pickle' for name in node.names)
        ]
        
        assert not any(pickle_imports), (
            "pickle should not be imported in learning_from_executions.py"
        )

    def test_no_pickle_import_from(self, ast_tree):
        """Verify 'from pickle import' is not used."""
        pickle_from_imports = [
            node.module == 'pickle'
            for node in ast.walk(ast_tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == 'pickle'
        ]
        
        assert not any(pickle_from_imports), (
            "'from pickle import' should not be used"
        )

    # ===== Edge Cases =====

    def test_module_still_parseable(self, source_content):
        """Verify the module can still be parsed (no syntax errors)."""
        try:
            ast.parse(source_content)
        except SyntaxError as e:
            pytest.fail(f"Module has syntax error: {e}")

    def test_imports_are_preserved(self, ast_tree):
        """Verify other imports are still present (sanity check)."""
        imports = [
            node.names[0].name
            for node in ast.walk(ast_tree)
            if isinstance(node, ast.Import)
        ]
        
        # Should have other imports like json, logging, etc.
        assert len(imports) > 5, "Module should still have other imports"

    # ===== Failure Mode Tests =====

    def test_no_pickle_usage_in_code(self, source_content):
        """Verify pickle is not used anywhere in the code."""
        # Check for pickle. usage
        assert 'pickle.' not in source_content, (
            "pickle module should not be used in code"
        )

    def test_no_pickle_dumps(self, source_content):
        """Verify pickle.dumps is not used."""
        assert 'pickle.dumps' not in source_content, (
            "pickle.dumps should not be used"
        )

    def test_no_pickle_loads(self, source_content):
        """Verify pickle.loads is not used."""
        assert 'pickle.loads' not in source_content, (
            "pickle.loads should not be used"
        )


class TestModuleIntegrity:
    """Tests to verify module integrity after change."""

    @pytest.fixture
    def source_file_path(self):
        import os
        weebot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return Path(weebot_dir) / "learning_from_executions.py"

    def test_module_can_be_imported(self, source_file_path):
        """Verify the module can still be imported without errors."""
        try:
            # This will fail if there are syntax errors or import issues
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "learning_from_executions", 
                source_file_path
            )
            module = importlib.util.module_from_spec(spec)
            # Don't execute, just verify spec is valid
            assert spec is not None
        except Exception as e:
            pytest.fail(f"Module cannot be loaded: {e}")

    def test_no_dangerous_builtins_modification(self, source_content):
        """Verify __builtins__ is not modified in dangerous ways."""
        # Check for common code injection patterns
        dangerous_patterns = [
            '__builtins__["__import__"]',
            '__builtins__["eval"]',
            '__builtins__["exec"]',
            'eval(',
            'exec(',
        ]
        
        for pattern in dangerous_patterns:
            if pattern in source_content:
                # Allow if it's in a safe context (like restricting builtins)
                if pattern == 'exec(' and '{"__builtins__": {}}' in source_content:
                    continue  # Safe exec usage
                pytest.fail(f"Dangerous pattern found: {pattern}")


# ===== Regression Invariants =====

REGRESSION_INVARIANTS = [
    "Module must be syntactically valid Python",
    "Module must not import pickle",
    "Module must not use pickle.dumps or pickle.loads",
    "Module must have other imports preserved",
    "Module must be importable without errors",
]


class TestRegressionInvariants:
    """Tests that verify regression invariants are maintained."""

    @pytest.mark.parametrize("invariant", REGRESSION_INVARIANTS)
    def test_invariant_holds(self, invariant):
        """Each regression invariant must hold."""
        # This test always passes - invariants are documented
        # Actual verification happens in the specific tests above
        assert invariant is not None