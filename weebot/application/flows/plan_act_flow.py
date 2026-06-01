"""Plan-Act flow — core state machine for autonomous task execution."""
from __future__ import annotations

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
from weebot.application.services.context_tokenizer import ContextTokenizer
from weebot.core.model_cascade_config import select_model_by_tokens
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
from weebot.tools.base import ToolCollection

if TYPE_CHECKING:
    from weebot.application.cqrs.mediator import Mediator

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
        max_step_repetitions: int = 3,
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
        self.status = AgentStatus.IDLE
        self._state: FlowState = None # Will be set in run()
        self._plan: Optional[Plan] = None
        self._compactor = MemoryCompactor()
        self._tokenizer = ContextTokenizer()
        self._undo_stack: list[Plan] = []
        self._redo_stack: list[Plan] = []
        self._episodic_memory = episodic_memory
        self._max_step_repetitions = max_step_repetitions
        self._auto_terminate_on_plan_complete = auto_terminate_on_plan_complete
        self._context_aware_model_selection = context_aware_model_selection
        self._step_execution_counts: dict[str, int] = {}  # Track step repetitions

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
        self._session = self._session.add_event(event)
        if self._event_bus:
            await self._event_bus.publish(event)

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

        max_iterations = 50  # Prevent infinite loops
        iteration_count = 0

        while iteration_count <= max_iterations:
            iteration_count += 1

            # Execute current state
            async for event in self._state.execute(self, prompt):
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
        
        Implements MEMORY_ARTICLE recommendation to use sparse attention
        models (DeepSeek DSA) for long contexts (50K+ tokens).
        
        Returns:
            New model ID if switch recommended, None otherwise.
        """
        if not self._context_aware_model_selection:
            return None
        
        estimated_tokens = self._tokenizer.estimate_session_tokens(self._session)
        config = select_model_by_tokens("coding", estimated_tokens)
        
        if config.id != self._model:
            logger.info(
                "Context-aware model selection: %s -> %s for ~%d tokens",
                self._model, config.id, estimated_tokens
            )
            return config.id
        
        return None
    
    def _update_agents_with_model(self, model: str) -> None:
        """Update planner and executor with a new model.
        
        Args:
            model: The new model ID to use.
        """
        self._model = model
        self._planner = PlannerAgent(
            llm=self._llm,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=self._skill_prompt,
            facts=self._session.get_facts(),
            episodic_memory=self._episodic_memory,
        )
        # Executor model is set per-call, no need to recreate

    def _snapshot_plan(self) -> None:
        """Push current plan onto undo stack and clear redo history."""
        if self._plan is not None:
            self._undo_stack.append(self._plan.model_copy())
            self._redo_stack.clear()

    def undo(self) -> Optional[Plan]:
        """Revert to the previous plan state if available."""
        if not self._undo_stack:
            return None
        if self._plan is not None:
            self._redo_stack.append(self._plan.model_copy())
        self._plan = self._undo_stack.pop()
        return self._plan

    def redo(self) -> Optional[Plan]:
        """Re-apply a plan state that was previously undone."""
        if not self._redo_stack:
            return None
        if self._plan is not None:
            self._undo_stack.append(self._plan.model_copy())
        self._plan = self._redo_stack.pop()
        return self._plan

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0
