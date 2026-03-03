#!/usr/bin/env python3
"""Verify release v2.1.0 is ready."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def check_version_file():
    """Check VERSION file exists and has correct value."""
    print("Checking VERSION file...")
    try:
        with open("VERSION") as f:
            version = f.read().strip()
        if version == "2.1.0":
            print(f"  ✅ VERSION = {version}")
            return True
        else:
            print(f"  ❌ VERSION = {version} (expected 2.1.0)")
            return False
    except FileNotFoundError:
        print("  ❌ VERSION file not found")
        return False


def check_changelog():
    """Check CHANGELOG.md exists."""
    print("Checking CHANGELOG.md...")
    if Path("CHANGELOG.md").exists():
        print("  ✅ CHANGELOG.md exists")
        return True
    else:
        print("  ❌ CHANGELOG.md not found")
        return False


def check_release_notes():
    """Check release notes exist."""
    print("Checking release notes...")
    if Path("RELEASE_NOTES_v2.1.0.md").exists():
        print("  ✅ RELEASE_NOTES_v2.1.0.md exists")
        return True
    else:
        print("  ❌ RELEASE_NOTES_v2.1.0.md not found")
        return False


def check_template_modules():
    """Check all template modules exist."""
    print("Checking template modules...")
    required = [
        "weebot/templates/__init__.py",
        "weebot/templates/parser.py",
        "weebot/templates/parameters.py",
        "weebot/templates/registry.py",
        "weebot/templates/engine.py",
        "weebot/templates/integration.py",
        "weebot/templates/agent_integration.py",
    ]
    
    all_exist = True
    for file in required:
        if Path(file).exists():
            print(f"  ✅ {file}")
        else:
            print(f"  ❌ {file} missing")
            all_exist = False
    
    return all_exist


def check_builtin_templates():
    """Check all 8 built-in templates exist."""
    print("Checking built-in templates...")
    required = [
        "research_analysis.yaml",
        "competitive_analysis.yaml",
        "data_processing.yaml",
        "code_review.yaml",
        "documentation.yaml",
        "bug_analysis.yaml",
        "meeting_summary.yaml",
        "learning_path.yaml",
    ]
    
    builtin_dir = Path("weebot/templates/builtin")
    all_exist = True
    
    for template in required:
        path = builtin_dir / template
        if path.exists():
            print(f"  ✅ {template}")
        else:
            print(f"  ❌ {template} missing")
            all_exist = False
    
    return all_exist


def check_tests():
    """Check test files exist."""
    print("Checking test files...")
    required = [
        "tests/unit/test_templates/test_parser.py",
        "tests/unit/test_templates/test_parameters.py",
        "tests/unit/test_templates/test_registry.py",
        "tests/unit/test_templates/test_engine.py",
        "tests/unit/test_templates/test_integration.py",
        "tests/unit/test_templates/test_agent_integration.py",
    ]
    
    all_exist = True
    for file in required:
        if Path(file).exists():
            print(f"  ✅ {file}")
        else:
            print(f"  ❌ {file} missing")
            all_exist = False
    
    return all_exist


def check_examples():
    """Check example files exist."""
    print("Checking examples...")
    required = [
        "examples/template_integration_example.py",
        "examples/agent_integration_example.py",
    ]
    
    all_exist = True
    for file in required:
        if Path(file).exists():
            print(f"  ✅ {file}")
        else:
            print(f"  ❌ {file} missing")
            all_exist = False
    
    return all_exist


def check_imports():
    """Check core imports work."""
    print("Checking imports...")
    try:
        from weebot.templates import (
            TemplateParser, WorkflowTemplate,
            ParameterResolver,
            TemplateRegistry,
            TemplateEngine,
        )
        print("  ✅ Core imports successful")
        return True
    except ImportError as e:
        print(f"  ❌ Import failed: {e}")
        return False


def check_readme_updated():
    """Check README mentions Template Engine."""
    print("Checking README.md...")
    try:
        with open("README.md") as f:
            content = f.read()
        
        checks = [
            "Template Engine" in content,
            "v2.1.0" in content or "2.1.0" in content,
            "weebot/templates/" in content,
        ]
        
        if all(checks):
            print("  ✅ README.md updated with Template Engine")
            return True
        else:
            print("  ⚠️  README.md may need updates")
            return True  # Warning, not error
    except FileNotFoundError:
        print("  ❌ README.md not found")
        return False


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("Release v2.1.0 Verification")
    print("=" * 60)
    print()
    
    checks = [
        ("VERSION file", check_version_file),
        ("CHANGELOG.md", check_changelog),
        ("Release notes", check_release_notes),
        ("Template modules", check_template_modules),
        ("Built-in templates", check_builtin_templates),
        ("Test files", check_tests),
        ("Examples", check_examples),
        ("Imports", check_imports),
        ("README.md", check_readme_updated),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            passed = check_func()
            results.append((name, passed))
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results.append((name, False))
        print()
    
    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print()
    print(f"Score: {passed_count}/{total_count} checks passed")
    print("=" * 60)
    
    if passed_count == total_count:
        print()
        print("🎉 Release v2.1.0 is READY!")
        print()
        print("Next steps:")
        print("  1. Run: ./release_v2.1.0.sh")
        print("  2. Create GitHub release")
        print("  3. Celebrate! 🚀")
        return 0
    else:
        print()
        print("⚠️  Some checks failed. Review above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
