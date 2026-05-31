"""CLI runner for the new Clean Architecture agent flows."""
from __future__ import annotations

import asyncio
import atexit
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.event import AgentEvent, WaitForUserEvent
from weebot.domain.models.session import Session, SessionStatus
from weebot.interfaces.cli.event_logger import CLIEventSubscriber
from weebot.interfaces.factories import build_tools, create_flow
from weebot.tools.base import ToolCollection
from weebot.core.behavior_integration import (
    start_session_tracking_async,
    stop_session_tracking_async,
    get_behavior_integration,
)


class AgentRunner:
    """High-level runner that encapsulates session lifecycle, flow execution, and event streaming."""

    def __init__(
        self,
        llm: LLMPort,
        state_repo: StateRepositoryPort,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        role: str = "admin",
        mcp_config: Optional[dict] = None,
        use_rich: bool = True,
        mediator = None,
        skill_prompt: Optional[str] = None,
    ) -> None:
        self._llm = llm
        self._state_repo = state_repo
        self._event_bus = event_bus
        self._model = model
        self._role = role
        self._mcp_config = mcp_config
        self._mediator = mediator
        self._skill_prompt = skill_prompt
        self._task_runner = TaskRunner(state_repo=state_repo, event_bus=event_bus)
        self._tools: Optional[ToolCollection] = None

        if event_bus and use_rich:
            CLIEventSubscriber(use_rich=use_rich).subscribe_to(event_bus)

    async def _ensure_tools(self) -> ToolCollection:
        if self._tools is None:
            self._tools = await build_tools(role=self._role, mcp_config=self._mcp_config)
        return self._tools

    async def run_prompt(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        user_id: str = "cli-user",
        agent_id: str = "weebot-cli",
    ) -> AsyncGenerator[AgentEvent, None]:
        """Run a prompt through PlanActFlow, yielding events."""
        session: Optional[Session] = None
        if session_id:
            session = await self._state_repo.load_session(session_id)

        if session is None:
            session = Session(
                id=session_id or str(uuid.uuid4()),
                user_id=user_id,
                agent_id=agent_id,
            )
            session = session.model_copy(update={"context": {"last_prompt": prompt}})
            await self._state_repo.save_session(session)
        else:
            session = session.model_copy(update={"context": {**session.context, "last_prompt": prompt}})
        
        # Start behavior tracking for this session
        behavior_tracker = await start_session_tracking_async(
            session_id=session.id,
            working_dir=Path.cwd(),
            user_id=user_id
        )
        
        if behavior_tracker:
            self._print_behavior_notice(session.id)

        tools = await self._ensure_tools()
        flow = create_flow(
            flow_type="plan_act",
            session=session,
            llm=self._llm,
            tools=tools,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=self._skill_prompt,
            mediator=self._mediator,
        )

        async for event in flow.run(prompt):
            session = session.add_event(event)
            # Set WAITING status before yielding a HITL event so the session
            # is resumable even if the consumer breaks the generator early.
            if isinstance(event, WaitForUserEvent):
                session = session.set_status(SessionStatus.WAITING)
            await self._state_repo.save_session(session)
            if self._event_bus:
                await self._event_bus.publish(event)
            yield event

        if flow.is_done():
            session = session.set_status(SessionStatus.COMPLETED)
        else:
            session = session.set_status(SessionStatus.WAITING)
        await self._state_repo.save_session(session)
        
        # Stop behavior tracking and show final report
        final_stats = await stop_session_tracking_async(session.id, generate_report=True)
        if final_stats:
            self._print_behavior_summary(final_stats)

    async def resume_session(
        self,
        session_id: str,
        answer: str,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Resume a waiting session by injecting a user answer.

        Runs the flow INLINE (not via background task runner) so the
        interactive loop waits for the step to complete before prompting
        for the next task.
        """
        tools = await self._ensure_tools()

        # Load and update the session synchronously
        session = await self._state_repo.load_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        if session.status != SessionStatus.WAITING:
            raise ValueError(
                f"Session {session_id} is not waiting (status: {session.status.value})"
            )

        session = session.add_user_message(answer)
        session = session.set_status(SessionStatus.RUNNING)
        await self._state_repo.save_session(session)

        # Run the flow inline — wait for completion
        flow = create_flow(
            flow_type="plan_act",
            session=session,
            llm=self._llm,
            tools=tools,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=self._skill_prompt,
            mediator=self._mediator,
        )

        async for event in flow.run(answer):
            session = session.add_event(event)
            if isinstance(event, WaitForUserEvent):
                session = session.set_status(SessionStatus.WAITING)
            await self._state_repo.save_session(session)
            if self._event_bus:
                await self._event_bus.publish(event)
            yield event

        if flow.is_done():
            session = session.set_status(SessionStatus.COMPLETED)
        else:
            session = session.set_status(SessionStatus.WAITING)
        await self._state_repo.save_session(session)

    async def list_sessions(self, user_id: Optional[str] = None) -> list[Session]:
        """List persisted sessions."""
        return await self._state_repo.list_sessions(user_id=user_id)

    async def flow_undo(self, session_id: str) -> bool:
        """Undo the last plan mutation for a loaded session by rehydrating its flow."""
        session = await self._state_repo.load_session(session_id)
        if session is None:
            return False
        tools = await self._ensure_tools()
        flow = create_flow(
            flow_type="plan_act",
            session=session,
            llm=self._llm,
            tools=tools,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=self._skill_prompt,
            mediator=self._mediator,
        )
        previous = flow.undo()
        if previous is None:
            return False
        session = session.model_copy(update={"context": {**session.context, "plan_undo": True}})
        await self._state_repo.save_session(session)
        return True

    async def cancel_session(self, session_id: str) -> bool:
        """Cancel a running session."""
        # Stop behavior tracking on cancel
        await stop_session_tracking_async(session_id, generate_report=False)
        return await self._task_runner.cancel_session(session_id)
    
    def _print_behavior_notice(self, session_id: str) -> None:
        """Print notice that behavior tracking is active."""
        try:
            from rich.console import Console
            from rich.panel import Panel
            console = Console()
            console.print(Panel(
                f"🔍 Behavior tracking active for session: {session_id[:8]}...\n"
                f"   All file changes are being recorded to ~/.weebot/ledger/",
                style="dim",
                border_style="blue"
            ))
        except Exception:
            print(f"\n🔍 Behavior tracking active: {session_id[:8]}...")
            print(f"   Recording to ~/.weebot/ledger/\n")
    
    def _print_behavior_summary(self, stats: dict) -> None:
        """Print behavior tracking summary."""
        try:
            from rich.console import Console
            from rich.panel import Panel
            console = Console()
            
            trust = stats.get('trust_score', 100)
            total = stats.get('trust_details', {}).get('total_actions', 0)
            
            style = "green" if trust >= 90 else "yellow" if trust >= 70 else "red"
            
            console.print(Panel(
                f"📊 Session Behavior Report\n"
                f"   Trust Score: {trust}% | Total Actions: {total}",
                style=style,
                border_style=style
            ))
        except Exception:
            trust = stats.get('trust_score', 100)
            total = stats.get('trust_details', {}).get('total_actions', 0)
            print(f"\n📊 Behavior Report: Trust={trust}%, Actions={total}\n")
