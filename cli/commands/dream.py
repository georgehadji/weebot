"""Dream CLI — scan, list, and build from IdeaContracts.

Usage:
    python -m cli.main dream scan          # Run DreamerAgent + IdeaGate cycle
    python -m cli.main dream list          # List pending Ideas
    python -m cli.main dream build <id>    # Run PlanActFlow on an approved Idea
"""
from __future__ import annotations

import asyncio
import logging

import click
from rich.console import Console
from rich.table import Table

from weebot.application.di import Container

logger = logging.getLogger(__name__)
console = Console()

# In-memory store for IdeaContracts (future: persist to DB)
_idea_store: dict[str, dict] = {}


@click.group()
def dream() -> None:
    """DreamAgent commands — idea scanning and gate chain."""
    pass


@dream.command("scan")
@click.option("--max-contracts", default=5, type=int, help="Max ideas to generate")
def dream_scan(max_contracts: int) -> None:
    """Run DreamerAgent + IdeaGate cycle and print approved ideas."""
    async def _run() -> None:
        container = Container()
        container.configure_defaults()

        dreamer = container.get("dreamer_agent")
        if dreamer is None:
            console.print("[red]DreamerAgent not configured in DI[/red]")
            return

        # Gather signals
        from weebot.application.ports.event_store_port import EventStorePort
        event_store = container.get(EventStorePort)
        failed_events = await event_store.query_recent_events(
            event_type="error", limit=30,
        ) if event_store else []

        # Dream
        console.print("[yellow]Dreaming...[/yellow]")
        contracts = await dreamer.dream(
            opportunity_proposals=[],
            failed_step_events=failed_events,
            audit_violations=[],
            session_id="dream_scan",
        )

        if not contracts:
            console.print("[dim]No ideas surfaced this cycle.[/dim]")
            return

        console.print(f"[green]Dreamer produced {len(contracts)} idea(s)[/green]")

        # Gate
        from weebot.application.services.intent_review_service import IntentReviewService
        from weebot.application.services.main_review_service import MainReviewService
        from weebot.application.services.idea_gate import IdeaGate
        from weebot.application.ports.llm_port import LLMPort

        llm = container.get(LLMPort)
        gate = IdeaGate(
            intent_reviewer=IntentReviewService(llm=llm),
            main_reviewer=MainReviewService(llm=llm),
        )
        approved = await gate.process(contracts)

        # Store for later use
        for c in approved:
            _idea_store[c.id] = c.model_dump()

        # Render table
        table = Table(title="Idea Contracts")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Heat", style="yellow")
        table.add_column("Effort", style="magenta")
        table.add_column("Status")

        for c in contracts:
            status = (
                "[green]APPROVED[/green]"
                if c.id in {a.id for a in approved}
                else f"[dim]{c.intent_verdict or c.main_verdict or 'pending'}[/dim]"
            )
            table.add_row(
                c.id[:12], c.title[:40],
                f"{c.heat_score:.2f}",
                c.estimated_effort,
                status,
            )
        console.print(table)

        if approved:
            console.print(
                f"\n[green]✓ {len(approved)} idea(s) approved.[/green] "
                "Run [bold]python -m cli.main dream build <id>[/bold] to execute."
            )

    asyncio.run(_run())


@dream.command("list")
def dream_list() -> None:
    """List pending IdeaContracts."""
    if not _idea_store:
        console.print("[dim]No ideas in store. Run 'dream scan' first.[/dim]")
        return

    table = Table(title="Stored IdeaContracts")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Heat", style="yellow")
    table.add_column("Intent", style="magenta")
    table.add_column("Main", style="blue")

    for cid, data in _idea_store.items():
        table.add_row(
            cid[:12],
            data.get("title", "?")[:40],
            f"{data.get('heat_score', 0):.2f}",
            data.get("intent_verdict", "—"),
            data.get("main_verdict", "—"),
        )
    console.print(table)


@dream.command("build")
@click.argument("contract_id")
def dream_build(contract_id: str) -> None:
    """Load an approved IdeaContract and run PlanActFlow on its prompt."""
    async def _run() -> None:
        data = _idea_store.get(contract_id)
        if data is None:
            console.print(f"[red]IdeaContract {contract_id} not found[/red]")
            return

        from weebot.domain.models.idea_contract import IdeaContract
        contract = IdeaContract(**data)

        from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
        from weebot.application.ports.state_repo_port import StateRepositoryPort
        from weebot.application.ports.llm_port import LLMPort
        from weebot.domain.models.session import Session

        container = Container()
        container.configure_defaults()

        llm = container.get(LLMPort)
        state_repo = container.get(StateRepositoryPort)
        session = Session(id=f"dream_{contract.id[:8]}", user_id="dreamer")
        await state_repo.save_session(session)

        from weebot.interfaces.cli.agent_runner import AgentRunner
        from weebot.interfaces.cli.event_logger import CLIEventSubscriber
        from weebot.domain.models.event import WaitForUserEvent

        runner = AgentRunner(
            llm=llm,
            state_repo=state_repo,
            mediator=container.get("mediator"),
            use_rich=False,
        )
        subscriber = CLIEventSubscriber(use_rich=True)

        console.print(f"[bold]Building idea: {contract.title}[/bold]")
        console.print(f"  Prompt: {contract.prompt[:100]}...")
        console.print()

        async for event in runner.run_prompt(contract.prompt, session_id=session.id):
            await subscriber.on_event(event)
            if isinstance(event, WaitForUserEvent):
                answer = input(f"\n[weebot asks] {event.question}\nYour answer: ")
                async for resume_event in runner.resume_session(session.id, answer):
                    await subscriber.on_event(resume_event)
                break

    asyncio.run(_run())
