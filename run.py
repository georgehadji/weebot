#!/usr/bin/env python3
"""run.py - Main entry point for weebot Agent Framework."""
import sys
import asyncio
import argparse
from weebot.config.settings import WeebotSettings


def validate_environment() -> None:
    """Validate .env configuration on startup.

    Raises:
        ValueError: If no AI API keys are configured.
    """
    settings = WeebotSettings()
    settings.validate_at_least_one_key()
    print(f"✓ weebot initialized with {len(settings.available_providers())} AI provider(s): {', '.join(settings.available_providers())}")


def run_cli() -> None:
    """Run the Click CLI interface."""
    from cli.main import cli
    cli()


def run_diagnostic() -> bool:
    """Run basic diagnostics to verify setup.

    Returns:
        bool: True if all modules loaded successfully, False otherwise.
    """
    print("=== weebot Diagnostics ===")
    errors = []

    modules = [
        ("weebot", "Core package"),
        ("weebot.config.settings", "Configuration"),
        ("weebot.ai_router", "AI Router"),
        ("weebot.agent_core_v2", "Agent Core"),
        ("weebot.state_manager", "State Manager"),
        ("weebot.notifications", "Notifications"),
        ("weebot.core.agent", "OEAR Agent"),
        ("weebot.core.safety", "Safety Checker"),
        ("weebot.tools.powershell_tool", "PowerShell Tool"),
        ("weebot.tools.browser_tool", "Browser Tool"),
        ("research_modules.reproducibility", "Research: Reproducibility"),
        ("research_modules.data_validator", "Research: Data Validator"),
        ("research_modules.literature", "Research: Literature"),
        ("integrations.obsidian", "Integration: Obsidian"),
        ("integrations.zotero", "Integration: Zotero"),
        ("cli.main", "CLI"),
    ]

    for module, label in modules:
        try:
            __import__(module)
            print(f"  [OK]  {label}")
        except ImportError as e:
            print(f"  [ERR] {label}: {e}")
            errors.append((label, str(e)))

    print()
    if errors:
        print(f"Found {len(errors)} import error(s). Check requirements.txt and .env.")
    else:
        print("All modules loaded successfully!")

    return len(errors) == 0

def run_interactive() -> None:
    """Run interactive agent session."""
    from weebot.agent_core_v2 import WeebotAgent, AgentConfig
    from weebot.ai_router import TaskType

    print("weebot Interactive Mode")
    print("Enter 'quit' to exit.\n")

    project_id = input("Project ID (default: interactive_session): ").strip() or "interactive_session"
    config = AgentConfig(project_id=project_id, description="Interactive session", daily_budget=5.0)
    agent = WeebotAgent(config)

    while True:
        task_desc = input("\nTask description: ").strip()
        if task_desc.lower() in ("quit", "exit", "q"):
            break
        if not task_desc:
            continue

        plan = [{
            "name": "user_task",
            "type": TaskType.CHAT,
            "description": task_desc,
            "prompt": task_desc,
        }]

        asyncio.run(agent.run(plan))
        print(agent.get_status())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="weebot Agent Framework")
    parser.add_argument("--diagnostic", action="store_true", help="Run diagnostics")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--cli", action="store_true", help="Run CLI (default)")
    args = parser.parse_args()

    try:
        validate_environment()
    except ValueError as e:
        print(f"\n{e}")
        sys.exit(1)

    if args.diagnostic:
        ok = run_diagnostic()
        sys.exit(0 if ok else 1)
    elif args.interactive:
        run_interactive()
    else:
        run_cli()
