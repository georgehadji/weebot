#!/usr/bin/env python3
"""run_linkedin_tasks.py — Execute 3 LinkedIn content creation tasks sequentially via weebot.

Usage:
    python scripts/run_linkedin_tasks.py              # run all 3 tasks
    python scripts/run_linkedin_tasks.py --task 1     # run a single task (1, 2, or 3)
    python scripts/run_linkedin_tasks.py --dry-run    # print prompts without executing

Tasks:
    1. LinkedIn Post Composer    — short-form post on communication skills
    2. LinkedIn Article Drafter  — long-form Pulse article on IC-to-lead transition
    3. LinkedIn Carousel Post    — multi-slide document post on saying "no" professionally
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# ── Environment setup (MUST run before weebot imports) ──
import os as _os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(override=True)

# Disable interactive gates for batch execution
_os.environ.setdefault("PLAN_REVIEW_ENABLED", "false")
_os.environ.setdefault("WEEBOT_PLAN_REVIEW_ENABLED", "false")
_os.environ.setdefault("COVE_ENABLED", "false")
_os.environ.setdefault("WEEBOT_COVE_ENABLED", "false")
_os.environ.setdefault("CONSTRAINT_CHECK_ENABLED", "false")
_os.environ.setdefault("CONTEXT_AWARE_MODEL_SELECTION", "false")

TASKS_DIR = PROJECT_ROOT / "tasks"

TASK_CONFIGS = [
    {
        "id": "linkedin_post_composer",
        "name": "LinkedIn Post Composer",
        "path": TASKS_DIR / "linkedin_post_composer",
        "description": "Write and post a short-form update on communication skills",
    },
    {
        "id": "linkedin_article_drafter",
        "name": "LinkedIn Article Drafter",
        "path": TASKS_DIR / "linkedin_article_drafter",
        "description": "Draft a Pulse article: 'From IC to Tech Lead — 5 Lessons'",
    },
    {
        "id": "linkedin_carousel_post",
        "name": "LinkedIn Carousel Post",
        "path": TASKS_DIR / "linkedin_carousel_post",
        "description": "Create multi-slide document post on saying 'no' professionally",
    },
]


def load_task_prompt(task_dir: Path) -> str | None:
    """Read the task.md file from a task directory and return its content."""
    task_md = task_dir / "task.md"
    if not task_md.exists():
        print(f"  [ERROR] task.md not found at {task_md}")
        return None
    return task_md.read_text(encoding="utf-8").strip()


async def run_single_task(
    task_config: dict,
    model: str | None = None,
    db_path: str = "./weebot_linkedin_tasks.db",
) -> bool:
    """Run one LinkedIn task through weebot's PlanActFlow."""
    from weebot.application.di import Container
    from weebot.application.services.model_selection import ModelSelectionService
    from weebot.config.model_refs import MODEL_BUDGET
    from weebot.interfaces.cli.agent_runner import AgentRunner
    from weebot.interfaces.cli.event_logger import CLIEventSubscriber
    from weebot.domain.models.event import WaitForUserEvent
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.application.cqrs.mediator import Mediator

    task_id = task_config["id"]
    task_name = task_config["name"]
    task_dir = task_config["path"]

    print(f"\n{'='*60}")
    print(f"  TASK: {task_name} ({task_id})")
    print(f"  {task_config['description']}")
    print(f"{'='*60}")

    prompt = load_task_prompt(task_dir)
    if not prompt:
        return False

    print(f"\n  Prompt ({len(prompt)} chars):")
    for line in prompt.splitlines()[:4]:
        print(f"    {line}")
    if prompt.count("\n") > 3:
        print(f"    ... ({prompt.count(chr(10)) + 1} lines total)")

    container = Container()
    container.configure_defaults(db_path=db_path, default_model=model)

    model_service = ModelSelectionService()
    llm = model_service.create_llm_adapter(model or MODEL_BUDGET)

    state_repo = container.get(StateRepositoryPort)
    mediator = container.get(Mediator)

    session_id = str(uuid.uuid4())
    runner = AgentRunner(
        llm=llm,
        state_repo=state_repo,
        mediator=mediator,
        model=model,
        use_rich=False,
    )
    subscriber = CLIEventSubscriber(use_rich=False)

    print(f"\n  Session: {session_id}")
    print(f"  Running...\n")

    try:
        async for event in runner.run_prompt(prompt, session_id=session_id):
            await subscriber.on_event(event)
            if isinstance(event, WaitForUserEvent):
                print(f"\n  [weebot asks] {event.question[:200]}...")
                print(f"  [auto-answer] proceed")
                try:
                    async for resume_event in runner.resume_session(session_id, "proceed"):
                        await subscriber.on_event(resume_event)
                except ValueError:
                    print(f"  [WARN] Resume failed (session may not be waiting) — continuing")
                break

        print(f"\n  [OK] Task '{task_name}' completed successfully.")
        return True

    except Exception as exc:
        print(f"\n  [FAIL] Task '{task_name}' failed: {exc}")
        return False
    finally:
        from weebot.infrastructure.persistence.connection_pool import close_all_pools

        await close_all_pools()


async def run_all_tasks(
    model: str | None = None,
    db_path: str = "./weebot_linkedin_tasks.db",
    dry_run: bool = False,
) -> None:
    """Run all 3 LinkedIn tasks sequentially."""
    results: list[dict] = []

    for i, task_config in enumerate(TASK_CONFIGS, 1):
        print(f"\n{'#'*60}")
        print(f"  LINKEDIN TASK {i} of {len(TASK_CONFIGS)}")
        print(f"{'#'*60}")

        if dry_run:
            prompt = load_task_prompt(task_config["path"])
            print(f"\n  [DRY RUN] Would run prompt:\n")
            print(f"  {prompt[:300]}...")
            results.append({"task": task_config["name"], "status": "dry_run"})
            continue

        success = await run_single_task(task_config, model=model, db_path=db_path)
        results.append(
            {"task": task_config["name"], "status": "pass" if success else "fail"}
        )

    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    dry = sum(1 for r in results if r["status"] == "dry_run")

    for r in results:
        icon = "✓" if r["status"] == "pass" else ("○" if r["status"] == "dry_run" else "✗")
        print(f"  {icon} {r['task']}: {r['status']}")

    print(f"\n  Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    if dry:
        print(f"  (Dry run — no tasks executed)")

    if failed:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run weebot LinkedIn content creation tasks sequentially",
    )
    parser.add_argument(
        "--task",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="Run a single task by number (1-3). Omit to run all.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the default LLM model.",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="./weebot_linkedin_tasks.db",
        help="SQLite database path for session state.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts without executing tasks.",
    )
    args = parser.parse_args()

    if args.task:
        task_config = TASK_CONFIGS[args.task - 1]
        if args.dry_run:
            prompt = load_task_prompt(task_config["path"])
            if prompt:
                print(f"Task {args.task}: {task_config['name']}")
                print(f"\n{prompt}")
        else:
            success = asyncio.run(
                run_single_task(task_config, model=args.model, db_path=args.db)
            )
            sys.exit(0 if success else 1)
    else:
        asyncio.run(
            run_all_tasks(model=args.model, db_path=args.db, dry_run=args.dry_run)
        )


if __name__ == "__main__":
    main()
