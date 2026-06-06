"""CLI commands for HyperAgent multi-agent workflows."""
from __future__ import annotations

import asyncio
import uuid

import click
from rich.console import Console
from rich.table import Table

from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort
from weebot.infrastructure.adapters.sub_agent_cost_tracker import SubAgentCostTracker
from weebot.domain.models.session import Session
from weebot.application.flows.hyper_agent_flow import HyperAgentFlow
from weebot.config.model_refs import MODEL_BUDGET
console = Console()


# NOTE: This Click group is NOT decorated with @cli.group() to avoid circular imports.
# Register in cli/main.py via: cli.add_command(hyper)
@click.group(name="hyper")
def hyper():
    """Multi-agent HyperAgent workflows."""


@hyper.command("run")
@click.argument("prompt", required=True)
@click.option("--session-id", default=None, help="Session identifier")
@click.option("--model", default=None, help="Override default LLM model")
@click.option("--max-concurrency", default=4, help="Max parallel sub-agents")
@click.option("--budget", default=0.50, help="Cost budget in USD")
def hyper_run(prompt: str, session_id: str | None, model: str | None,
              max_concurrency: int, budget: float):
    """Run a multi-agent HyperAgent workflow with the given prompt."""
    async def _run() -> None:
        container = Container()
        container.configure_defaults()

        llm = container.get(LLMPort)
        state_repo = container.get(StateRepositoryPort)
        swarm_bus = container.get(SwarmEventBusPort)
        factory = container.get(SubAgentFactoryPort)
        cost_tracker = SubAgentCostTracker(budget_usd=budget)
        run_session_id = session_id or str(uuid.uuid4())

        session = Session(
            id=run_session_id,
            user_id="cli",
            agent_id="hyper_agent",
        )

        flow = HyperAgentFlow(
            llm=llm,
            session=session,
            event_bus=container.get(EventBusPort),
            swarm_bus=swarm_bus,
            sub_agent_factory=factory,
            cost_tracker=cost_tracker,
            model=model or MODEL_BUDGET,
            max_concurrency=max_concurrency,
        )

        console.print(f"[bold blue]HyperAgent[/bold blue] session: {run_session_id}")

        async for event in flow.run(prompt):
            etype = getattr(event, "type", "") or getattr(event, "event_type", "")
            if etype == "error":
                error_msg = getattr(event, "error", "") or str(event)
                console.print(f"[red]Error: {error_msg}[/red]")
            elif etype == "message":
                content = getattr(event, "message", "") or getattr(event, "content", "")
                console.print(content[:2000])
            elif etype in ("plan", "step", "tool"):
                pass  # internal flow events
            else:
                console.print(f"[dim]{etype}[/dim]")

        print()
        cost_info = cost_tracker.summary()
        console.print(f"[dim]Budget: ${cost_info['budget_usd']:.2f} | "
                      f"Spent: ${cost_info['total_spent_usd']:.3f} | "
                      f"Remaining: ${cost_info['remaining_usd']:.3f}[/dim]")

    asyncio.run(_run())


@hyper.command("list-costs")
@click.option("--session-id", default=None, help="Filter by session")
def hyper_list_costs(session_id: str | None):
    """List completed HyperAgent workflows and their costs."""
    async def _run() -> None:
        container = Container()
        container.configure_defaults()
        state_repo = container.get(StateRepositoryPort)
        sessions = await state_repo.list_sessions()
        table = Table(title="HyperAgent Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Title", style="green")

        for s in sessions:
            table.add_row(
                s.id[:20],
                s.status.value,
                (s.title or "")[:40],
            )
        console.print(table)

    asyncio.run(_run())
