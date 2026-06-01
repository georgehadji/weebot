#!/usr/bin/env python3
"""run.py - Main entry point for weebot Agent Framework."""
import sys
import asyncio
import argparse
from pathlib import Path
import structlog
from dotenv import load_dotenv
from weebot.config.settings import WeebotSettings


# Load .env into os.environ so os.getenv() works everywhere.
# override=True ensures .env takes precedence over stale system env vars
load_dotenv(override=True)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

# Clear the adapter cache on every startup so stale model names
# and expired API keys are never reused from a previous run.
from weebot.infrastructure.adapters.llm import adapter_factory as _af
_af.get_adapter_factory().clear_cache()
_af._default_factory = None


def validate_environment() -> None:
    """Validate .env configuration on startup.

    Raises:
        ValueError: If no AI API keys are configured.
    """
    settings = WeebotSettings()
    settings.validate_at_least_one_key()
    print(f"weebot initialized with {len(settings.available_providers())} AI provider(s): {', '.join(settings.available_providers())}")


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


def run_interactive(flow_type: str = "plan_act", model: str | None = None, skill: str | None = None) -> None:
    """Run interactive agent session using the new Clean Architecture flows."""
    from weebot.application.di import Container
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.interfaces.cli.agent_runner import AgentRunner
    from weebot.interfaces.cli.event_logger import CLIEventSubscriber
    from weebot.domain.models.event import WaitForUserEvent
    from weebot.application.services.model_selection import ModelSelectionService

    # Load skill if specified
    skill_prompt = None
    if skill:
        skill_path = Path(__file__).parent / "weebot" / "skills" / f"{skill}.md"
        if skill_path.exists():
            skill_prompt = skill_path.read_text(encoding="utf-8")
            print(f"  Loaded skill: {skill} ({len(skill_prompt)} chars)")
        else:
            print(f"  [WARN] Skill file not found: {skill_path}")

    async def _main() -> None:
        # Use ModelSelectionService to pick the right adapter
        model_service = ModelSelectionService()
        # Use a free model by default. Override with --model or env DEFAULT_MODEL.
        import os as _os
        # Default model from centralized definition
        from weebot.config.model_refs import MODEL_BUDGET
        _default = _os.environ.get("DEFAULT_MODEL", MODEL_BUDGET)
        llm = model_service.create_llm_adapter(model or _default)
        _container = Container()
        _container.configure_defaults()
        state_repo = _container.get(StateRepositoryPort)
        runner = AgentRunner(llm=llm, state_repo=state_repo, model=model, use_rich=False, skill_prompt=skill_prompt)
        subscriber = CLIEventSubscriber(use_rich=True)

        print("weebot Interactive Mode (PlanActFlow)")
        print("Enter 'quit' to exit.\n")

        session_id = input("Session ID (default: interactive_session): ").strip() or "interactive_session"

        while True:
            prompt = input("\nTask description: ").strip()
            if prompt.lower() in ("quit", "exit", "q"):
                break
            if not prompt:
                continue

            async for event in runner.run_prompt(prompt, session_id=session_id):
                await subscriber.on_event(event)
                if isinstance(event, WaitForUserEvent):
                    answer = input(f"\n[weebot asks] {event.question}\nYour answer: ")
                    async for resume_event in runner.resume_session(session_id, answer):
                        await subscriber.on_event(resume_event)
                    break

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="weebot Agent Framework")
    parser.add_argument("--diagnostic", action="store_true", help="Run diagnostics")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--cli", action="store_true", help="Run CLI (default)")
    parser.add_argument("--flow", default="plan_act", help="Flow type for interactive mode (default: plan_act)")
    parser.add_argument("--model", default=None, help="Override default LLM model")
    parser.add_argument("--skill", default=None, help="Load a skill file from weebot/skills/<name>.md")
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
        run_interactive(flow_type=args.flow, model=args.model, skill=args.skill)
    else:
        run_cli()
