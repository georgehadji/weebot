"""Plan-Act flow — core state machine for autonomous task execution."""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import AsyncGenerator, Optional, TYPE_CHECKING

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.agents.planner import PlannerAgent
from weebot.application.flows.base_flow import BaseFlow
from weebot.application.flows.states.base import FlowState
from weebot.application.flows.states.planning import PlanningState
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.updating import UpdatingState
from weebot.application.flows.states.summarizing import SummarizingState
from weebot.application.flows.states.completed import CompletedState

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.services.memory_compactor import MemoryCompactor
from weebot.application.services.context_switcher import ContextSwitcher
from weebot.application.services.plan_history import PlanHistory
from weebot.application.services.continuation_detector import (
    ContinuationDetector,
)
from weebot.domain.models.event import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    PlanEvent,
    PlanStatus,
    StepEvent,
    StepStatus,
    WaitForUserEvent,
)
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus
from weebot.application.models.tool_collection import ToolCollection

if TYPE_CHECKING:
    from weebot.application.cqrs.mediator import Mediator
    from weebot.application.ports.state_repo_port import StateRepositoryPort

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    UPDATING = "updating"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"


class PlanActFlow(BaseFlow):
    """Plan-Act agent flow with explicit state machine."""

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolCollection,
        session: Session,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        skill_prompt: Optional[str] = None,
        episodic_memory = None,
        mediator: Optional[Mediator] = None,
        state_repo: Optional[StateRepositoryPort] = None,
        max_step_repetitions: int = 3,
        max_iterations: int = 50,
        auto_terminate_on_plan_complete: bool = True,
        context_aware_model_selection: bool = True,
        max_steps: Optional[int] = None,
    ):
        self._llm = llm
        self._tools = tools
        self._session = session
        self._event_bus = event_bus
        self._model = model
        self._mediator = mediator
        self._state_repo = state_repo
        self.status = AgentStatus.IDLE
        self._state: FlowState = None # Will be set in run()
        self._plan: Optional[Plan] = None
        self._compactor = MemoryCompactor()
        self._plan_history = PlanHistory()
        self._context_switcher = ContextSwitcher(llm=self._llm, event_bus=self._event_bus)
        self._episodic_memory = episodic_memory
        self._max_step_repetitions = max_step_repetitions
        self._auto_terminate_on_plan_complete = auto_terminate_on_plan_complete
        self._context_aware_model_selection = context_aware_model_selection
        self._max_iterations = max_iterations
        self._step_execution_counts: dict[str, int] = {}  # Track step repetitions
        self._emit_lock = asyncio.Lock()

        self._skill_prompt = skill_prompt
        self._planner = PlannerAgent(
            llm=self._llm,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=skill_prompt,
            facts=session.get_facts(),
            episodic_memory=episodic_memory,
        )
        executor_kwargs = dict(
            llm=self._llm,
            tools=self._tools,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=skill_prompt,
        )
        if max_steps is not None:
            executor_kwargs["max_steps"] = max_steps
        self._executor = ExecutorAgent(**executor_kwargs)

    async def _emit(self, event: AgentEvent) -> None:
        async with self._emit_lock:
            self._session = self._session.add_event(event)
            if self._event_bus:
                await self._event_bus.publish(event)
            if self._state_repo:
                await self._state_repo.save_session(self._session)

    def is_done(self) -> bool:
        return self._session.status == SessionStatus.COMPLETED

    def set_state(self, state: FlowState) -> None:
        """Change the current flow state."""
        state_map = {
            PlanningState: AgentStatus.PLANNING,
            ExecutingState: AgentStatus.EXECUTING,
            UpdatingState: AgentStatus.UPDATING,
            SummarizingState: AgentStatus.SUMMARIZING,
            CompletedState: AgentStatus.COMPLETED,
        }
        self._state = state
        self.status = state_map.get(type(state), AgentStatus.IDLE)
        logger.info("Transition to state: %s", type(state).__name__)

    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        logger.info("PlanActFlow started for session %s", self._session.id)

        # --- Task context preservation ---
        # Store the first substantive prompt so short follow-ups ("proceed", "yes")
        # can be enriched with it when a brand-new plan is needed.
        original_task: str = self._session.context.get("_original_task", "")
        if not original_task and prompt.strip():
            original_task = prompt.strip()
            self._session = self._session.model_copy(
                update={"context": self._session.context.model_copy(
                    update={"original_task": original_task}
                )}
            )

        # Resolve effective prompt — enrich vague continuations via service
        effective_prompt = ContinuationDetector.resolve_prompt(
            user_prompt=prompt,
            original_task=original_task,
            event_count=len(self._session.events),
        )

        # Initial Resume/Start logic
        last_plan = self._session.get_last_plan()

        if last_plan is not None and not last_plan.is_complete():
            self._plan = last_plan
            self.set_state(ExecutingState())
            logger.info("Resuming session %s with existing plan", self._session.id)
        elif self._session.status == SessionStatus.WAITING:
            self.set_state(ExecutingState())
            logger.info("Session %s was waiting, continuing execution", self._session.id)
        else:
            self.set_state(PlanningState())

        max_iterations = self._max_iterations
        iteration_count = 0

        while iteration_count <= max_iterations:
            iteration_count += 1

            # Execute current state
            async for event in self._state.execute(self, effective_prompt):
                yield event

            # If we reached COMPLETED state logic or it paused for HITL, we break
            if self._session.status in (SessionStatus.COMPLETED, SessionStatus.WAITING):
                break

            # If we are IDLE after state execution, we might be finished
            if self.status == AgentStatus.IDLE:
                break

        if iteration_count > max_iterations:
            yield ErrorEvent(error=f"Max iterations ({max_iterations}) reached.")

    def _has_unresolved_wait_event(self) -> bool:
        """Check if the last WaitForUserEvent in the session has not been resolved."""
        return self._session.has_unresolved_wait_event()

    def _maybe_switch_model_for_context(self) -> Optional[str]:
        """Dynamically select model based on context size if enabled.

        Delegates to ContextSwitcher service.

        Returns:
            New model ID if switch recommended, None otherwise.
        """
        return self._context_switcher.maybe_switch_model_for_context(
            session=self._session,
            current_model=self._model,
            context_aware_enabled=self._context_aware_model_selection,
        )

    def _update_agents_with_model(self, model: str) -> None:
        """Update planner with a new model via ContextSwitcher.

        Args:
            model: The new model ID to use.
        """
        self._model = model
        self._planner = self._context_switcher.update_agents_with_model(
            model=model,
            skill_prompt=self._skill_prompt,
            facts=self._session.get_facts(),
            episodic_memory=self._episodic_memory,
        )

    def _snapshot_plan(self) -> None:
        """Push current plan onto the PlanHistory undo stack."""
        self._plan_history.snapshot(self._plan)

    def undo(self) -> Optional[Plan]:
        """Revert to the previous plan state if available."""
        self._plan = self._plan_history.undo(self._plan)
        return self._plan

    def redo(self) -> Optional[Plan]:
        """Re-apply a plan state that was previously undone."""
        self._plan = self._plan_history.redo(self._plan)
        return self._plan

    @property
    def can_undo(self) -> bool:
        return self._plan_history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._plan_history.can_redo
