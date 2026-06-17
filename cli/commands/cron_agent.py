"""Cron Agent CLI commands — manage cron-scheduled agent tasks.

Usage:
    python -m cli.main cron-agent create "0 8 * * 1" "Summarize commits" --skills git
    python -m cli.main cron-agent list
    python -m cli.main cron-agent enable <id>
    python -m cli.main cron-agent disable <id>
    python -m cli.main cron-agent delete <id>
    python -m cli.main cron-agent run <id>   # manual run
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from weebot.domain.models.cron_job import CronJobRecord, DeliveryTarget, DeliveryTargetType

console = Console()
logger = logging.getLogger(__name__)

# File-based persistence for cron jobs (simple JSON store)
CRON_JOBS_PATH = Path.home() / ".weebot" / "cron_jobs.json"


def _load_jobs() -> dict[str, dict]:
    if CRON_JOBS_PATH.exists():
        try:
            return json.loads(CRON_JOBS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_jobs(jobs: dict[str, dict]) -> None:
    CRON_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRON_JOBS_PATH.write_text(json.dumps(jobs, indent=2, default=str), encoding="utf-8")


@click.group("cron-agent")
def cron_agent() -> None:
    """Manage cron-scheduled agent tasks."""
    pass


@cron_agent.command("create")
@click.argument("schedule")
@click.argument("prompt")
@click.option("--name", default=None, help="Job name (defaults to auto-generated)")
@click.option("--skills", default=None, help="Comma-separated skill names")
@click.option("--toolsets", default="automation", help="Comma-separated toolset names (default: automation)")
@click.option("--deliver-to", default=None, help="Delivery target type: telegram|discord|slack|file|none")
@click.option("--deliver-dest", default=None, help="Delivery destination (chat ID, file path, etc.)")
@click.option("--max-runtime", default=300, help="Max runtime in seconds")
@click.option("--model", default=None, help="Model override")
def cron_create(schedule: str, prompt: str, name: str | None,
                skills: str | None, toolsets: str | None,
                deliver_to: str | None, deliver_dest: str | None,
                max_runtime: int, model: str | None) -> None:
    """Create a new cron agent job.

    SCHEDULE: Cron expression (e.g., "0 8 * * 1") or interval (e.g., "30min").

    PROMPT: Task description for the agent.
    """
    job_id = f"cron-{uuid.uuid4().hex[:8]}"
    job_name = name or f"Cron-{job_id[:8]}"

    # Parse delivery target
    delivery = DeliveryTarget()
    if deliver_to and deliver_to != "none":
        try:
            delivery = DeliveryTarget(
                type=DeliveryTargetType(deliver_to.lower()),
                destination=deliver_dest,
            )
        except ValueError:
            console.print(f"[red]Invalid delivery type: {deliver_to}. "
                          f"Choose from: telegram, discord, slack, file, none[/red]")
            return

    # Parse skills and toolsets
    skill_list = [s.strip() for s in skills.split(",")] if skills else []
    toolset_list = [t.strip() for t in toolsets.split(",")] if toolsets else ["automation"]

    # Validate with Pydantic
    try:
        job = CronJobRecord(
            id=job_id,
            name=job_name,
            schedule=schedule,
            prompt=prompt,
            attached_skills=skill_list,
            attached_toolsets=toolset_list,
            model=model,
            deliver_to=delivery,
            max_runtime_seconds=max_runtime,
        )
    except Exception as exc:
        console.print(f"[red]Invalid job configuration: {exc}[/red]")
        return

    # Persist
    jobs = _load_jobs()
    jobs[job_id] = job.model_dump(mode="json")
    _save_jobs(jobs)

    console.print(f"[green]Created cron job: {job_id}[/green]")
    console.print(f"  Name:     {job_name}")
    console.print(f"  Schedule: {schedule}")
    console.print(f"  Prompt:   {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    if skill_list:
        console.print(f"  Skills:   {', '.join(skill_list)}")
    console.print(f"  Delivery: {delivery.type.value}" +
                  (f" → {delivery.destination}" if delivery.destination else ""))


@cron_agent.command("list")
def cron_list() -> None:
    """List all cron agent jobs."""
    jobs = _load_jobs()

    if not jobs:
        console.print("[yellow]No cron agent jobs configured.[/yellow]")
        return

    table = Table(title="Cron Agent Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Schedule", style="blue")
    table.add_column("Enabled", style="green")
    table.add_column("Runs", style="white")
    table.add_column("Last Run", style="yellow")

    for jid, data in jobs.items():
        enabled = "✅" if data.get("enabled", True) else "❌"
        last_run = data.get("last_run_at") or "never"
        if isinstance(last_run, str) and len(last_run) > 16:
            last_run = last_run[:16]
        table.add_row(
            jid[:12],
            data.get("name", ""),
            data.get("schedule", ""),
            enabled,
            str(data.get("run_count", 0)),
            str(last_run),
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(jobs)} job(s)[/dim]")


@cron_agent.command("enable")
@click.argument("job_id")
def cron_enable(job_id: str) -> None:
    """Enable a cron agent job."""
    jobs = _load_jobs()
    if job_id not in jobs:
        # Try prefix match
        matches = [jid for jid in jobs if jid.startswith(job_id)]
        if len(matches) == 1:
            job_id = matches[0]
        else:
            console.print(f"[red]Job not found: {job_id}[/red]")
            return

    jobs[job_id]["enabled"] = True
    _save_jobs(jobs)
    console.print(f"[green]Enabled cron job: {job_id}[/green]")


@cron_agent.command("disable")
@click.argument("job_id")
def cron_disable(job_id: str) -> None:
    """Disable a cron agent job."""
    jobs = _load_jobs()
    if job_id not in jobs:
        matches = [jid for jid in jobs if jid.startswith(job_id)]
        if len(matches) == 1:
            job_id = matches[0]
        else:
            console.print(f"[red]Job not found: {job_id}[/red]")
            return

    jobs[job_id]["enabled"] = False
    _save_jobs(jobs)
    console.print(f"[yellow]Disabled cron job: {job_id}[/yellow]")


@cron_agent.command("delete")
@click.argument("job_id")
@click.confirmation_option(prompt="Are you sure?")
def cron_delete(job_id: str) -> None:
    """Delete a cron agent job."""
    jobs = _load_jobs()
    if job_id not in jobs:
        matches = [jid for jid in jobs if jid.startswith(job_id)]
        if len(matches) == 1:
            job_id = matches[0]
        else:
            console.print(f"[red]Job not found: {job_id}[/red]")
            return

    del jobs[job_id]
    _save_jobs(jobs)
    console.print(f"[red]Deleted cron job: {job_id}[/red]")


@cron_agent.command("run")
@click.argument("job_id")
def cron_run(job_id: str) -> None:
    """Manually run a cron agent job."""
    jobs = _load_jobs()
    if job_id not in jobs:
        matches = [jid for jid in jobs if jid.startswith(job_id)]
        if len(matches) == 1:
            job_id = matches[0]
        else:
            console.print(f"[red]Job not found: {job_id}[/red]")
            return

    data = jobs[job_id]
    job = CronJobRecord(**data)

    console.print(f"[yellow]Running cron job: {job.name} ({job_id})...[/yellow]")

    from weebot.application.services.cron_agent_runner import CronAgentRunner
    from weebot.application.di import Container

    container = Container()
    container.configure_defaults()

    runner = CronAgentRunner(
        llm=container.get("llm_port"),
        state_repo=container.get("state_repo_port"),
        tool_registry=None,
    )

    result = asyncio.run(runner.run(job))

    console.print(Panel(result, title=f"Job Result: {job.name}", style="green"))

    # Update job record
    jobs[job_id]["last_run_at"] = datetime.utcnow().isoformat()
    jobs[job_id]["last_result"] = result[:500]
    jobs[job_id]["run_count"] = data.get("run_count", 0) + 1
    _save_jobs(jobs)


if __name__ == "__main__":
    cron_agent()
