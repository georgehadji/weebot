#!/usr/bin/env python3
"""Verify the new built-in templates load correctly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from weebot.templates import TemplateParser

TEMPLATES = [
    "code_review.yaml",
    "documentation.yaml",
    "bug_analysis.yaml",
    "meeting_summary.yaml",
    "learning_path.yaml",
]

def main():
    print("=" * 60)
    print("Verifying New Built-in Templates")
    print("=" * 60)
    
    parser = TemplateParser()
    builtin_dir = Path("weebot/templates/builtin")
    
    results = []
    for template_file in TEMPLATES:
        path = builtin_dir / template_file
        try:
            template = parser.parse_file(path)
            print(f"\n✅ {template.name}")
            print(f"   Version: {template.version}")
            print(f"   Parameters: {len(template.parameters)}")
            print(f"   Workflow tasks: {len(template.workflow)}")
            results.append((template_file, True, None))
        except Exception as e:
            print(f"\n❌ {template_file}")
            print(f"   Error: {e}")
            results.append((template_file, False, str(e)))
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    
    for name, ok, error in results:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
        if error:
            print(f"     {error}")
    
    print(f"\nScore: {passed}/{total} templates valid")
    
    if passed == total:
        print("\n🎉 All new templates are valid!")
        return 0
    else:
        print("\n⚠️ Some templates have errors")
        return 1

if __name__ == "__main__":
    sys.exit(main())
