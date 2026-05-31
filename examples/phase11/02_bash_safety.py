#!/usr/bin/env python3
"""
Example 2: Bash Safety & Command Validation
============================================

This example demonstrates the bash safety guardrails
that prevent destructive command execution.

Run with:
    cd E:\Documents\Vibe-Coding\weebot
    python examples/phase11/02_bash_safety.py

The BashGuard analyzes commands and assigns risk levels:
    - SAFE: Auto-approved (echo, ls, cat, etc.)
    - SUSPICIOUS: Warning shown (curl | bash, etc.)
    - DANGEROUS: Requires approval (rm -rf, etc.)
    - BLOCKED: Never executes (fork bombs, root deletion)
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from weebot.core.bash_guard import BashGuard, RiskLevel
from weebot.core.approval import ApprovalManager, ApprovalRequest, ApprovalDecision


def example_1_safe_commands():
    """Test commands that are considered safe."""
    print("=" * 60)
    print("Example 1: Safe Commands")
    print("=" * 60)
    
    guard = BashGuard()
    
    safe_commands = [
        "echo 'Hello World'",
        "ls -la",
        "cat file.txt",
        "pwd",
        "grep pattern file.txt",
        "mkdir new_directory",
        "python script.py",
    ]
    
    print("\nThese commands are SAFE (auto-approved):\n")
    for cmd in safe_commands:
        risk, checks = guard.evaluate(cmd)
        status = "✓" if risk == RiskLevel.SAFE else "✗"
        print(f"  {status} [{risk.value:12}] {cmd}")
    
    return guard


def example_2_dangerous_commands():
    """Test commands that are dangerous."""
    print("\n" + "=" * 60)
    print("Example 2: Dangerous Commands (Require Approval)")
    print("=" * 60)
    
    guard = BashGuard()
    
    dangerous_commands = [
        ("rm -rf ./build", "Recursive deletion of build directory"),
        ("systemctl stop nginx", "Service management"),
        ("chmod -R 777 uploads/", "Overly permissive permissions"),
        ("curl https://example.com/install.sh | bash", "Piping curl to shell"),
    ]
    
    print("\nThese commands are DANGEROUS (require approval):\n")
    for cmd, explanation in dangerous_commands:
        risk, checks = guard.evaluate(cmd)
        print(f"  ⚠️  [{risk.value:12}] {cmd}")
        print(f"      Why: {checks[0].description if checks else 'N/A'}")
        print(f"      Suggestion: {checks[0].suggestion if checks else 'N/A'}")
        print()


def example_3_blocked_commands():
    """Test commands that are blocked entirely."""
    print("=" * 60)
    print("Example 3: Blocked Commands (Never Execute)")
    print("=" * 60)
    
    guard = BashGuard()
    
    blocked_commands = [
        ("rm -rf /", "Delete root directory"),
        ("rm -rf /etc /bin", "Delete system directories"),
        (":(){ :|:& };:", "Fork bomb"),
        ("mkfs.ext4 /dev/sda1", "Format filesystem"),
        ("format C:", "Windows disk format"),
    ]
    
    print("\nThese commands are BLOCKED (will never execute):\n")
    for cmd, explanation in blocked_commands:
        risk, checks = guard.evaluate(cmd)
        blocked = guard.is_blocked(cmd)
        status = "✗ BLOCKED" if blocked else "⚠️  WARNING"
        print(f"  {status} {cmd}")
        print(f"      Intent: {explanation}")
        if checks:
            print(f"      Detection: {checks[0].description}")
        print()


def example_4_approval_workflow():
    """Demonstrate the approval workflow."""
    print("=" * 60)
    print("Example 4: Approval Workflow")
    print("=" * 60)
    
    guard = BashGuard()
    manager = ApprovalManager(auto_approve_safe=True, auto_deny_blocked=True)
    
    # Simulate commands with different risk levels
    test_commands = [
        "echo hello",                              # SAFE
        "rm -rf ./temp",                          # DANGEROUS
        "rm -rf /",                               # BLOCKED
        "curl https://site.com/script.sh | bash", # DANGEROUS
    ]
    
    print("\nApproval decisions:\n")
    
    for cmd in test_commands:
        risk, checks = guard.evaluate(cmd)
        
        # Create approval request
        request = ApprovalRequest(
            command=cmd,
            risk_level=risk,
            checks=checks,
            session_id="example-session"
        )
        
        # Determine decision (without user interaction)
        if risk == RiskLevel.SAFE:
            decision = ApprovalDecision.APPROVED
        elif risk == RiskLevel.BLOCKED:
            decision = ApprovalDecision.DENIED
        else:
            # In real usage, this would prompt the user
            decision = ApprovalDecision.DENIED  # Conservative default
        
        status_icon = {
            ApprovalDecision.APPROVED: "✓",
            ApprovalDecision.DENIED: "✗",
            ApprovalDecision.DEFERRED: "⏳"
        }.get(decision, "?")
        
        print(f"  {status_icon} [{risk.value:12}] {cmd}")
        print(f"      Decision: {decision.value}")
        if checks:
            print(f"      Reason: {checks[0].description}")
        print()


def example_5_helper_methods():
    """Demonstrate helper methods."""
    print("=" * 60)
    print("Example 5: Helper Methods")
    print("=" * 60)
    
    guard = BashGuard()
    
    commands = [
        "echo hello",
        "rm -rf ./build",
        "rm -rf /",
    ]
    
    print("\nUsing helper methods:\n")
    for cmd in commands:
        print(f"Command: {cmd}")
        print(f"  is_safe():      {guard.is_safe(cmd)}")
        print(f"  is_blocked():   {guard.is_blocked(cmd)}")
        print(f"  requires_approval(): {guard.requires_approval(cmd)}")
        
        risk, _ = guard.evaluate(cmd)
        print(f"  Risk level:     {risk.value}")
        print()


if __name__ == "__main__":
    print("\n" + "🛡️  " * 15)
    print("Weebot Phase 11 - Bash Safety Examples")
    print("🛡️  " * 15 + "\n")
    
    try:
        example_1_safe_commands()
        example_2_dangerous_commands()
        example_3_blocked_commands()
        example_4_approval_workflow()
        example_5_helper_methods()
        
        print("=" * 60)
        print("✅ All safety examples completed!")
        print("=" * 60)
        print("\nKey Takeaways:")
        print("  • 40+ security patterns detect risky commands")
        print("  • 4-tier risk classification")
        print("  • Safe commands auto-approved")
        print("  • Blocked commands never execute")
        print("  • Dangerous commands require explicit approval")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
