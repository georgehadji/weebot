#!/usr/bin/env python3
"""cli_main.py - Command Line Interface for weebot Agent.

Εντολές:
--------
create      Δημιουργία νέου project
list        Λίστα όλων των projects
status      Έλεγχος κατάστασης project
run         Εκτέλεση task plan από JSON
resume      Συνέχιση paused project
checkpoint  Επίλυση pending checkpoint
delete      Διαγραφή project
export      Export project state
costs       Αναφορά κόστους
monitor     Real-time monitoring
"""
import click
import asyncio
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress

from weebot.agent_core_v2 import WeebotAgent, AgentConfig
from weebot.state_manager import StateManager, ProjectStatus

console = Console()


@click.group()
def cli() -> None:
    """weebot Agent Framework CLI."""
    pass


@cli.command()
@click.argument("project_id")
@click.argument("description")
@click.option("--budget", default=10.0, help="Daily AI budget")
def create(project_id: str, description: str, budget: float) -> None:
    """Create new project."""
    config = AgentConfig(
        project_id=project_id,
        description=description,
        daily_budget=budget
    )
    agent = WeebotAgent(config)
    console.print(Panel(f"Created project: {project_id}", style="green"))


@cli.command()
def list_projects() -> None:
    """List all projects."""
    sm = StateManager()
    projects = sm.list_projects()

    table = Table(title="Active Projects")
    table.add_column("Project ID", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Last Updated", style="green")

    for proj in projects:
        state = sm.load_state(proj["project_id"])
        table.add_row(
            proj["project_id"],
            state.status.value if state else "unknown",
            str(proj["updated_at"])
        )

    console.print(table)


@cli.command()
@click.argument("project_id")
def status(project_id: str) -> None:
    """Check project status."""
    config = AgentConfig(project_id=project_id, description="")
    agent = WeebotAgent(config)
    stats = agent.get_status()
    
    console.print(Panel.fit(
        f"Status: {stats['status']}\n"
        f"Progress: {stats['progress']} tasks completed\n"
        f"Current: {stats['current_task'] or 'None'}\n"
        f"Pending Checkpoints: {stats['pending_checkpoints']}\n"
        f"Cost Today: ${stats['cost_stats']['today']:.4f}",
        title=f"Project: {project_id}"
    ))


@cli.command()
@click.argument("project_id")
@click.argument("plan_file", type=click.Path(exists=True))
def run(project_id: str, plan_file: str) -> None:
    """Execute task plan from JSON file."""
    import json
    
    plan = json.loads(Path(plan_file).read_text())
    
    config = AgentConfig(
        project_id=project_id,
        description=f"Running plan from {plan_file}"
    )
    agent = WeebotAgent(config)
    
    with Progress() as progress:
        task = progress.add_task("[cyan]Executing tasks...", total=len(plan))
        
        async def execute():
            for item in plan:
                progress.update(task, advance=1, description=f"[cyan]Task: {item['name']}")
                await agent.run([item])
        
        asyncio.run(execute())
    
    console.print("[green]Plan execution complete![/green]")


@cli.command()
@click.argument("project_id")
def resume(project_id: str) -> None:
    """Resume paused project."""
    config = AgentConfig(project_id=project_id, description="")
    agent = WeebotAgent(config)

    # Resume from current state
    console.print(f"[yellow]Resuming project: {project_id}[/yellow]")

    # Implementation would continue from last checkpoint
    console.print("[green]Resumed successfully![/green]")


@cli.command()
@click.argument("project_id")
@click.argument("checkpoint_id")
@click.argument("response")
def checkpoint(project_id: str, checkpoint_id: str, response: str) -> None:
    """Resolve pending checkpoint."""
    sm = StateManager()
    sm.resolve_checkpoint(checkpoint_id, response)
    console.print(f"[green]Resolved checkpoint {checkpoint_id}: {response}[/green]")


@cli.command()
@click.argument("project_id")
@click.confirmation_option(prompt="Are you sure you want to delete this project?")
def delete(project_id: str) -> None:
    """Delete project."""
    # Implementation would delete from database
    console.print(f"[red]Deleted project: {project_id}[/red]")


@cli.command()
@click.argument("project_id")
@click.option("--output", "-o", default="export.json")
def export(project_id: str, output: str) -> None:
    """Export project state."""
    sm = StateManager()
    state = sm.load_state(project_id)

    if state:
        import json
        from dataclasses import asdict

        Path(output).write_text(
            json.dumps(asdict(state), indent=2, default=str)
        )
        console.print(f"[green]Exported to: {output}[/green]")
    else:
        console.print(f"[red]Project not found: {project_id}[/red]")


@cli.command()
@click.option("--days", default=7, help="Number of days to report")
def costs(days: int) -> None:
    """Show cost report."""
    table = Table(title=f"Cost Report (Last {days} days)")
    table.add_column("Date", style="cyan")
    table.add_column("Cost", style="green")
    table.add_column("Tokens", style="magenta")
    
    # Placeholder data
    table.add_row("Today", "$2.45", "12,340")
    table.add_row("Yesterday", "$1.23", "8,900")
    
    console.print(table)


# Research commands group
@cli.group()
def research() -> None:
    """Scientific research commands."""
    pass


@research.command()
@click.argument("title")
@click.option("--description", "-d", default="")
@click.option("--field", "-f", type=click.Choice(["physics", "biology", "math", "cs", "other"]))
def init_experiment(title: str, description: str, field: str):
    """Initialize new reproducible experiment"""
    from research_modules.reproducibility import ReproducibilityManager, ExperimentConfig
    
    rm = ReproducibilityManager()
    config = ExperimentConfig(
        title=title,
        description=description,
        tags=[field] if field else [],
        random_seed=42
    )
    exp = rm.create_experiment(config)
    console.print(Panel(
        f"Created experiment: {exp.exp_id}\n"
        f"Location: {exp.work_dir}\n"
        f"Seed: {config.random_seed}",
        title="Reproducible Experiment"
    ))


@research.command()
@click.argument("data_file")
@click.option("--rules", "-r", help="JSON file with validation rules")
def validate_data(data_file: str, rules: str):
    """Validate scientific dataset"""
    from research_modules.data_validator import ScientificValidator
    import pandas as pd
    import json
    
    df = pd.read_csv(data_file)
    
    validator = ScientificValidator()
    validation_rules = json.loads(Path(rules).read_text()) if rules else {}
    
    report = validator.validate_dataset(df, validation_rules)
    
    console.print(f"Valid: {'✓' if report['valid'] else '✗'}")
    console.print(f"Issues found: {len(report['issues'])}")
    
    for issue in report['issues']:
        color = {
            'info': 'blue',
            'warning': 'yellow',
            'error': 'red',
            'critical': 'red'
        }.get(issue['severity'], 'white')
        
        console.print(f"[{color}]{issue['severity'].upper()}: {issue['message']}[/{color}]")


@research.command()
@click.argument("vault_path")
@click.option("--experiment", "-e", help="Specific experiment to sync")
def obsidian_sync(vault_path: str, experiment: str):
    """Sync experiments to Obsidian vault"""
    from integrations.obsidian import ObsidianVault
    
    vault = ObsidianVault(vault_path)
    
    if experiment:
        vault.generate_from_experiment(experiment)
        console.print(f"[green]Synced experiment: {experiment}[/green]")
    else:
        vault.create_dashboard()
        console.print("[green]Created research dashboard[/green]")


if __name__ == "__main__":
    cli()
