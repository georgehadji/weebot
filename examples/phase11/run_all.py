#!/usr/bin/env python3
"""
Run all Phase 11 examples
==========================

This script runs all examples in sequence with nice formatting.

Usage:
    python run_all.py
    python run_all.py --quick  (run faster, less output)
"""

import subprocess
import sys
import time
from pathlib import Path


EXAMPLES = [
    ("01_basic_usage.py", "Structured Output"),
    ("02_bash_safety.py", "Bash Safety"),
    ("03_event_logging.py", "Event Logging"),
]


def print_header():
    """Print welcome header."""
    print("\n" + "=" * 70)
    print(" " * 20 + "WEEBOT PHASE 11 EXAMPLES")
    print("=" * 70)
    print("\nThis will run all examples demonstrating Phase 11 features:")
    print("  1. Structured Output Protocol")
    print("  2. Bash Safety Guardrails")
    print("  3. Event Logging & Cost Tracking\n")
    print("=" * 70 + "\n")


def print_footer(elapsed):
    """Print completion footer."""
    print("\n" + "=" * 70)
    print("✅ All examples completed successfully!")
    print(f"⏱️  Total time: {elapsed:.2f} seconds")
    print("=" * 70)
    print("\nNext steps:")
    print("  • Try: python -m cli.main flow run 'Your task'")
    print("  • Or:  python run.py --interactive")
    print("  • Read: examples/phase11/README.md")
    print()


def run_example(script_name, description):
    """Run a single example script."""
    script_path = Path(__file__).parent / script_name
    
    print(f"\n{'─' * 70}")
    print(f"▶️  Running: {script_name}")
    print(f"   Description: {description}")
    print('─' * 70 + "\n")
    
    start = time.time()
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=False,
            text=True,
            check=True,
        )
        elapsed = time.time() - start
        print(f"\n✅ {script_name} completed in {elapsed:.2f}s")
        return True
        
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start
        print(f"\n❌ {script_name} failed after {elapsed:.2f}s")
        print(f"   Error code: {e.returncode}")
        return False
        
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n❌ {script_name} failed after {elapsed:.2f}s")
        print(f"   Error: {e}")
        return False


def main():
    """Main entry point."""
    print_header()
    
    # Check if examples exist
    for script, _ in EXAMPLES:
        script_path = Path(__file__).parent / script
        if not script_path.exists():
            print(f"❌ Example not found: {script}")
            print(f"   Expected: {script_path}")
            sys.exit(1)
    
    # Run all examples
    start_total = time.time()
    results = []
    
    for script, desc in EXAMPLES:
        success = run_example(script, desc)
        results.append((script, success))
        
        if not success:
            print("\n⚠️  Stopping due to failure")
            break
    
    elapsed_total = time.time() - start_total
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    for script, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {status} {script}")
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        print_footer(elapsed_total)
        sys.exit(0)
    else:
        print("\n" + "=" * 70)
        print("❌ Some examples failed!")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
