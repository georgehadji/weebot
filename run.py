#!/usr/bin/env python3
"""run.py - Main entry point for weebot Agent Framework."""
import os
import sys
import asyncio
import argparse
from pathlib import Path
import structlog
from dotenv import load_dotenv

# ═══ Load .env BEFORE any weebot imports ═══
# WORKSPACE_ROOT in settings.py is evaluated at import time from
# os.getenv("WEEBOT_WORKSPACE", os.getcwd()).  load_dotenv MUST run first
# so the .env value takes effect, otherwise the workspace defaults to cwd
# and path validation inconsistently rejects valid workspace paths.
load_dotenv(override=True)

from weebot.config.settings import WeebotSettings

# Clear stale bytecode cache to prevent import errors from old .pyc files
import shutil as _shutil
_root = Path(__file__).parent
_count = 0
for _pyc in _root.rglob("__pycache__"):
    try:
        _shutil.rmtree(_pyc)
        _count += 1
    except OSError:
        pass
if _count:
    print(f"  Cleared {_count} stale bytecode cache(s)")

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


def run_interactive(
    flow_type: str = "plan_act",
    model: str | None = None,
    skill: str | None = None,
    skillopt: bool = False,
) -> None:
    """Run interactive agent session using the new Clean Architecture flows."""
    from weebot.application.di import Container
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.interfaces.cli.agent_runner import AgentRunner
    from weebot.interfaces.cli.event_logger import CLIEventSubscriber
    from weebot.domain.models.event import WaitForUserEvent
    from weebot.domain.models.session import SessionStatus
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

        # ── Phase 5: Steering — wire up mid-execution input channel ──
        from weebot.application.ports.steering_port import SteeringPort
        steering = _container.get(SteeringPort)

        subscriber = CLIEventSubscriber(use_rich=True)

        print("weebot Interactive Mode (PlanActFlow)")
        print("Type '>>' followed by a message to steer the agent mid-execution.")
        print("Enter 'quit' to exit.\n")

        session_id = input("Session ID (default: interactive_session): ").strip() or "interactive_session"
        
        # Check if session exists and show status
        session = await state_repo.load_session(session_id)
        if session:
            print(f"  Joining session: {session_id} (Status: {session.status.value})")
            if session.get_last_plan():
                plan = session.get_last_plan()
                done = len([s for s in plan.steps if s.is_done()])
                print(f"  Current Plan: {plan.title} ({done}/{len(plan.steps)} steps complete)")

        from weebot.application.cqrs.mediator import Mediator
        runner = AgentRunner(
            llm=llm, state_repo=state_repo, model=model,
            use_rich=False, skill_prompt=skill_prompt,
            steering=steering,
            mediator=_container.get(Mediator),
        )

        while True:
            # More conversational prompt
            prompt_text = "Task / Answer: " if session and session.status == SessionStatus.WAITING else "Task description: "
            raw = input(f"\n{prompt_text}").strip()

            # ">>" prefix sends a steering message mid-execution (no new task)
            if raw.startswith(">>") and len(raw) > 2:
                steer_msg = raw[2:].strip()
                if steer_msg and steering:
                    steering.send_threadsafe(session_id, steer_msg)
                    print(f"  (steering sent: {steer_msg})")
                continue

            if raw.lower() in ("quit", "exit", "q"):
                break
            if not raw:
                # If session is waiting, empty input might mean "continue"
                if session and session.status == SessionStatus.WAITING:
                    raw = "continue"
                else:
                    continue
            
            # Recursive prompt handler for HITL
            current_prompt = raw
            while True:
                is_hitl = False
                hitl_question = ""
                
                # Execute (either run_prompt for new/starting or resume for waiting)
                # Note: run_prompt handles both if session exists.
                async for event in runner.run_prompt(current_prompt, session_id=session_id):
                    await subscriber.on_event(event)
                    if isinstance(event, WaitForUserEvent):
                        is_hitl = True
                        hitl_question = event.question
                        # We break the async for to get the next answer from user
                        break
                
                # Update our local session state to check status
                session = await state_repo.load_session(session_id)
                
                if is_hitl:
                    current_prompt = input(f"\n[weebot asks] {hitl_question}\nYour answer: ").strip()
                    if not current_prompt:
                        current_prompt = "yes" # default to affirmative
                else:
                    # No more HITL, go back to main task description prompt
                    break

        # ── Post-session SkillOpt (opt-in via --skillopt or WEEBOT_SKILLOPT=1) ──
        if skillopt:
            print("\n🧪 Running SkillOptFlow learning pass...")
            await _run_skillopt_pass()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")


async def _run_skillopt_pass() -> None:
    """Run a single lightweight SkillOpt pass on available skills.

    Uses 1 epoch × 2 steps to keep cost low.  Full training runs
    are available via ``python -m cli.main flow skillopt <name>``.
    """
    import os as _os
    from weebot.application.di import Container

    container = Container()
    container.configure_defaults()

    try:
        container.configure_skillopt()
    except Exception as exc:
        print(f"  [WARN] SkillOpt wiring failed: {exc}")
        return

    # Discover available skills
    from weebot.application.skills.skill_registry import SkillRegistry
    registry = SkillRegistry()
    registry.load_all()
    skills = registry.list_names()

    if not skills:
        print("  No skills found in registry — skipping SkillOpt.")
        return

    print(f"  Found {len(skills)} skill(s): {', '.join(skills[:5])}")
    if len(skills) > 5:
        print(f"  ... and {len(skills) - 5} more. Optimizing first 3.")

    optimized = 0
    for skill_name in skills[:3]:
        try:
            flow = container.build_skill_opt_flow(
                skill_name=skill_name,
                train_tasks=[],
                validation_tasks=None,
                output_path=f"{skill_name}.md",
                epochs=1,
                steps_per_epoch=2,
                batch_size=16,
                use_planning=False,
            )
            async for event in flow.run():
                etype = getattr(event, "type", "")
                if etype == "epoch_completed":
                    e = event
                    print(
                        f"    {skill_name}: best={e.best_validation_score:.3f}  "
                        f"accepted={e.edits_accepted}  rejected={e.edits_rejected}"
                    )
            optimized += 1
        except Exception as exc:
            print(f"    [WARN] {skill_name}: {exc}")

    if optimized:
        print(f"  SkillOpt complete — {optimized} skill(s) processed.\n")
    else:
        print("  SkillOpt: no skills processed.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="weebot Agent Framework")
    parser.add_argument("--diagnostic", action="store_true", help="Run diagnostics")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--cli", action="store_true", help="Run CLI (default)")
    parser.add_argument("--flow", default="plan_act", help="Flow type for interactive mode (default: plan_act)")
    parser.add_argument("--model", default=None, help="Override default LLM model")
    parser.add_argument("--skill", default=None, help="Load a skill file from weebot/skills/<name>.md")
    parser.add_argument(
        "--skillopt", action="store_true",
        default=os.environ.get("WEEBOT_SKILLOPT", "0") == "1",
        help="Run SkillOptFlow learning pass after interactive session "
             "(set WEEBOT_SKILLOPT=1 in .env to enable by default)",
    )
    parser.add_argument(
        "--harness-version", default=os.environ.get("WEEBOT_HARNESS_VERSION"),
        help="Select harness version (YAML file name in config/harness/)",
    )
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
        run_interactive(flow_type=args.flow, model=args.model, skill=args.skill, skillopt=args.skillopt)
    else:
        run_cli()
