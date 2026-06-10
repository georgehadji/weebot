"""Domain-level agent abstractions (pure logic, no infrastructure).

The actual LLM-driven one-step executor lives in application layer.
This provides the core protocol and simple state transitions.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Protocol, Optional
from .models import Plan, Step, ExecutionResult, AgentState, Task


class AgentProtocol(Protocol):
    """Protocol for any agent that can execute one step at a time."""

    def execute_next_step(self, state: AgentState) -> ExecutionResult:
        """Execute exactly ONE step from the current plan. Never the whole plan."""
        ...

    def decompose_goal(self, task: Task) -> Plan:
        """Create a plan (list of steps) for the given task. Pure decomposition."""
        ...


class BaseAgent(ABC):
    """Abstract base for domain agents. Enforces one-step rule."""

    @abstractmethod
    def execute_next_step(self, state: AgentState) -> ExecutionResult:
        """Must execute exactly one step. Update state accordingly."""
        raise NotImplementedError

    def validate_one_step_rule(self, plan: Plan) -> bool:
        """Domain rule: plans are executed one step at a time."""
        current = plan.get_current_step()
        if current is None:
            return False
        # Only one step should be IN_PROGRESS at any time (enforced by caller)
        in_progress = [
            s for s in plan.steps
            if s.status == StepStatus.IN_PROGRESS
        ]
        return len(in_progress) <= 1
