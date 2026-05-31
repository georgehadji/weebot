#!/usr/bin/env python3
"""
Example 1: Basic Weebot Usage
=============================

This example demonstrates basic structured output parsing
and simple agent interactions.

Run with:
    cd E:\Documents\Vibe-Coding\weebot
    python examples/phase11/01_basic_usage.py

Or from project root:
    python -m examples.phase11.01_basic_usage

Requirements:
    - Weebot installed or PYTHONPATH set
    - No API keys needed (uses mock data)
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from weebot.models.structured_output import (
    WeebotOutput,
    TaskStatus,
    CodeChange,
    BashCommand,
    parse_agent_output,
    create_system_prompt,
)


def example_1_basic_output():
    """Create and inspect a basic structured output."""
    print("=" * 60)
    print("Example 1: Creating Structured Output")
    print("=" * 60)
    
    # Create a structured output manually
    output = WeebotOutput(
        status=TaskStatus.SUCCESS,
        message="Created a Python script for calculating Fibonacci",
        reasoning="The user requested a Fibonacci calculator. I created a clean implementation with docstring and type hints.",
        code_changes=[
            CodeChange(
                file_path="fibonacci.py",
                change_type="create",
                description="Fibonacci calculator function",
                reasoning="User needs to calculate Fibonacci numbers",
                code="""def fibonacci(n: int) -> int:
    '''Calculate the nth Fibonacci number.'''
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

if __name__ == "__main__":
    for i in range(10):
        print(f"F({i}) = {fibonacci(i)}")"""
            )
        ],
        bash_commands=[
            BashCommand(
                command="python fibonacci.py",
                purpose="Test the Fibonacci implementation",
                requires_approval=False,
                timeout_seconds=30
            )
        ],
        confidence=0.95,
        estimated_complexity=3,
        estimated_cost=0.02,
        tokens_used=150,
        model_used="qwen/qwen3-coder-30b:free"
    )
    
    print(f"\nStatus: {output.status.value}")
    print(f"Message: {output.message}")
    print(f"Confidence: {output.confidence}")
    print(f"Estimated Cost: ${output.estimated_cost}")
    print(f"\nCode Changes:")
    for change in output.code_changes:
        print(f"  - {change.change_type}: {change.file_path}")
        print(f"    Description: {change.description}")
        print(f"    Code preview: {change.code[:50]}...")
    
    print(f"\nBash Commands:")
    for cmd in output.bash_commands:
        print(f"  - {cmd.command}")
        print(f"    Purpose: {cmd.purpose}")
        print(f"    Requires Approval: {cmd.requires_approval}")
    
    return output


def example_2_parse_json():
    """Parse JSON output from an agent."""
    print("\n" + "=" * 60)
    print("Example 2: Parsing Agent JSON Output")
    print("=" * 60)
    
    # Simulate an agent response with markdown JSON
    agent_response = """```json
{
    "status": "partial",
    "message": "I need more information to complete this task",
    "reasoning": "The request is ambiguous - I don't know which sorting algorithm to use",
    "requires_user_input": true,
    "suggested_questions": [
        "Which sorting algorithm do you prefer? (bubble, quick, merge)",
        "Should it sort in ascending or descending order?"
    ],
    "confidence": 0.3,
    "estimated_complexity": 5
}
```"""
    
    # Parse the response
    parsed = parse_agent_output(agent_response)
    
    print(f"\nParsed Output:")
    print(f"  Status: {parsed.status.value}")
    print(f"  Message: {parsed.message}")
    print(f"  Confidence: {parsed.confidence}")
    print(f"  Requires Input: {parsed.requires_user_input}")
    print(f"\n  Suggested Questions:")
    for q in parsed.suggested_questions:
        print(f"    - {q}")
    
    return parsed


def example_3_parse_failure():
    """Handle parse failures gracefully."""
    print("\n" + "=" * 60)
    print("Example 3: Handling Invalid JSON")
    print("=" * 60)
    
    # Invalid response
    bad_response = "This is not JSON at all, just free text from the agent"
    
    parsed = parse_agent_output(bad_response)
    
    print(f"\nInput: {bad_response}")
    print(f"\nParsed Output:")
    print(f"  Status: {parsed.status.value}")
    print(f"  Message (truncated): {parsed.message}")
    print(f"  Reasoning: {parsed.reasoning}")
    print(f"  Requires Input: {parsed.requires_user_input}")
    print(f"\n  → System knows the agent was confused and can ask for clarification")
    
    return parsed


def example_4_system_prompt():
    """Display the system prompt for structured output."""
    print("\n" + "=" * 60)
    print("Example 4: System Prompt Preview")
    print("=" * 60)
    
    prompt = create_system_prompt()
    
    print(f"\nPrompt length: {len(prompt)} characters")
    print("\nFirst 500 characters:")
    print("-" * 40)
    print(prompt[:500])
    print("-" * 40)
    print("... (truncated)")
    
    return prompt


if __name__ == "__main__":
    print("\n" + "🤖 " * 20)
    print("Weebot Phase 11 - Basic Usage Examples")
    print("🤖 " * 20 + "\n")
    
    try:
        example_1_basic_output()
        example_2_parse_json()
        example_3_parse_failure()
        example_4_system_prompt()
        
        print("\n" + "=" * 60)
        print("✅ All examples completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
