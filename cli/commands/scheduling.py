"""CLI commands — cron"""
from __future__ import annotations
from pathlib import Path

import click
from rich.console import Console

console = Console()

@click.group()
def cron() -> None:
    """Schedule recurring tasks with natural language."""
    pass


@cron.command("schedule")
@click.argument("schedule_text", nargs=-1, required=True)
@click.option("--task", required=True, help="Task description to execute")
@click.option("--name", default=None, help="Job name (default: auto-generated)")
def cron_schedule(schedule_text: tuple[str, ...], task: str, name: str | None) -> None:
    """Schedule a recurring task using natural language.

    SCHEDULE_TEXT is a natural-language schedule like
    "every Friday at 2pm" or "every 3 hours".

    Example:
        weebot cron schedule "every day at 9am" --task "Run daily report"
        weebot cron schedule "every Monday" --task "Weekly security audit"
    """
    import asyncio

    async def _run() -> None:
        from weebot.scheduling.nl_cron import parse_schedule
        from weebot.scheduling.scheduler import SchedulingManager
        import uuid

        text = " ".join(schedule_text)
        parsed = parse_schedule(text)

        if parsed is None:
            console.print(
                f"[red]✗[/red] Could not parse schedule: '{text}'. "
                "Try: 'every day at 9am', 'every Monday at 2pm', "
                "'every 3 hours'."
            )
            return

        job_id = f"cron-{uuid.uuid4().hex[:8]}"
        job_name = name or f"Scheduled: {task[:40]}"

        # Store the schedule in jobs.yaml or create an in-memory job
        mgr = SchedulingManager()
        try:
            from apscheduler.triggers.cron import CronTrigger
            trigger = CronTrigger.from_crontab(parsed["cron_expression"])
            await mgr.create_job(
                job_id=job_id,
                name=job_name,
                description=task,
                trigger_type="cron",
                trigger_config={"cron_expression": parsed["cron_expression"]},
                callable_name="_nl_cron_executor",
            )
            console.print(
                f"[green]✓[/green] Scheduled: [cyan]{job_name}[/cyan]\n"
                f"  Schedule: {parsed['description']} ({parsed['cron_expression']})\n"
                f"  Task: {task}"
            )
        except Exception as exc:
            console.print(f"[red]✗[/red] Failed to schedule: {exc}")

    asyncio.run(_run())


@cron.command("list")
def cron_list() -> None:
    """List all scheduled cron jobs."""
    import asyncio

    async def _run() -> None:
        from weebot.scheduling.scheduler import SchedulingManager
        from rich.table import Table

        mgr = SchedulingManager()
        jobs = await mgr.list_jobs()

        if not jobs:
            console.print("[dim]No scheduled jobs.[/dim]")
            return

        table = Table(title="Scheduled Jobs")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Schedule")
        table.add_column("Enabled", style="green")

        for j in jobs:
            schedule = j.trigger_config.get("cron_expression", j.trigger_type) if hasattr(j, "trigger_config") else j.trigger_type
            enabled = "✓" if getattr(j, "enabled", True) else "✗"
            table.add_row(
                getattr(j, "job_id", "?")[:12],
                getattr(j, "name", "?")[:40],
                str(schedule)[:20],
                enabled,
            )
        console.print(table)

    asyncio.run(_run())


@cron.command("remove")
@click.argument("job_id")
def cron_remove(job_id: str) -> None:
    """Remove a scheduled job by ID."""
    import asyncio

    async def _run() -> None:
        from weebot.scheduling.scheduler import SchedulingManager

        mgr = SchedulingManager()
        await mgr.remove_job(job_id)
        console.print(f"[green]✓[/green] Removed job '[cyan]{job_id}[/cyan]'")

    asyncio.run(_run())


@click.command()
def companion() -> None:
    """Start the Windows desktop companion (system tray + global hotkey).
    Requires optional dependencies: pystray, keyboard, and tkinter.
    """
    import asyncio
    async def _run():
        from weebot.interfaces.windows import run_companion
        await run_companion()


