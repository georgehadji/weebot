"""CLI event subscriber that pretty-prints agent events."""
from __future__ import annotations

from typing import Awaitable, Callable

from weebot.application.ports.event_bus_port import EventBusPort, EventHandler
from weebot.domain.models.event import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    MessageEvent,
    PlanEvent,
    StepEvent,
    ThoughtEvent,
    TitleEvent,
    ToolEvent,
    WaitForUserEvent,
)


def _format_event(event: AgentEvent) -> str:
    if isinstance(event, TitleEvent):
        return f"\n[bold cyan]📋 {event.title}[/bold cyan]"
    if isinstance(event, PlanEvent):
        return "[dim]Plan created/updated[/dim]"
    if isinstance(event, StepEvent):
        if event.status.value == "completed":
            return f"  ✅ Step {event.step_id}: {event.description} (completed)"
        elif event.status.value == "failed":
            return f"  ❌ Step {event.step_id}: {event.description} (failed)"
        return f"  ▶️ Step {event.step_id}: {event.description} ({event.status.value})"
    if isinstance(event, ToolEvent):
        if event.status.value == "calling":
            return f"    🔧 Calling {event.tool_name}({event.function_args})"
        return f"    🔧 {event.tool_name} -> {str(event.result)[:120]}"
    if isinstance(event, MessageEvent):
        return f"  💬 {event.message}"
    if isinstance(event, ThoughtEvent):
        return f"    [dim italic]🤔 {event.thought}[/dim italic]"
    if isinstance(event, WaitForUserEvent):
        return f"\n[bold yellow]❓ {event.question}[/bold yellow]"
    if isinstance(event, ErrorEvent):
        return f"\n[bold red]⚠️ Error: {event.error}[/bold red]"
    if isinstance(event, DoneEvent):
        return "\n[bold green]✨ Done[/bold green]"
    return str(event)


class CLIEventSubscriber:
    """Subscriber that prints events to the console."""

    def __init__(self, use_rich: bool = True) -> None:
        self.use_rich = use_rich

    async def on_event(self, event: AgentEvent) -> None:
        line = _format_event(event)
        if self.use_rich:
            try:
                from rich.console import Console
                Console().print(line)
                return
            except Exception:
                pass
        # Safe print with encoding fallback
        try:
            print(line)
        except UnicodeEncodeError:
            # Fallback for Windows terminals without UTF-8
            safe_line = line.encode('ascii', 'ignore').decode('ascii')
            print(safe_line)

    def subscribe_to(self, bus: EventBusPort) -> None:
        bus.subscribe(self.on_event)
