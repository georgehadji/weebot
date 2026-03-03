#!/usr/bin/env python3
"""
Test runner for Phase 3 template tests.
Usage: python run_template_tests.py [test_file_name]

Examples:
  python run_template_tests.py              # Run all template tests
  python run_template_tests.py test_parser  # Run only parser tests
  python run_template_tests.py test_parameters  # Run only parameter tests
"""
import sys
import subprocess
from pathlib import Path

def main():
    # Get project root
    project_root = Path(__file__).parent
    
    # Determine which tests to run
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        if not test_file.startswith("test_"):
            test_file = f"test_{test_file}"
        if not test_file.endswith(".py"):
            test_file = f"{test_file}.py"
        test_path = f"tests/unit/test_templates/{test_file}"
    else:
        test_path = "tests/unit/test_templates/"
    
    # Build pytest command
    cmd = [
        sys.executable, "-m", "pytest",
        test_path,
        "-v",
        "--tb=short"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    print(f"Working directory: {project_root}")
    print("=" * 60)
    
    # Run tests
    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
