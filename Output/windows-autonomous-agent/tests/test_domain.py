"""RED -> GREEN tests for the domain layer.

These tests validate core domain models (Plan, Step, Task, ExecutionResult, AgentState)
and the one-step execution rule from the architecture.
All tests must pass for GREEN phase.
"""
import pytest
from datetime import datetime
from domain.models import (
    Task, Plan, Step, StepStatus, PlanStatus, ExecutionResult, AgentState
)
from domain.agent import BaseAgent, AgentProtocol


class TestDomainModels:
    """Test Pydantic domain entities."""

    def test_task_creation(self):
        task = Task(id="t1", description="Build a Windows autonomous agent")
        assert task.id == "t1"
        assert "autonomous agent" in task.description
        assert isinstance(task.created_at, datetime)

    def test_step_creation_and_validation(self):
        step = Step(id="s1", description="Create domain models using Pydantic")
        assert step.status == StepStatus.PENDING
        assert step.tool_name is None
        # Empty description should fail
        with pytest.raises(ValueError):
            Step(id="s2", description="   ")

    def test_plan_get_current_step(self):
        steps = [
            Step(id="s1", description="Step one"),
            Step(id="s2", description="Step two"),
        ]
        plan = Plan(id="p1", task_id="t1", steps=steps, current_step_index=0)
        current = plan.get_current_step()
        assert current is not None
        assert current.id == "s1"
        assert current.status == StepStatus.PENDING

    def test_plan_mark_step_completed_advances_index(self):
        steps = [
            Step(id="s1", description="First"),
            Step(id="s2", description="Second"),
        ]
        plan = Plan(id="p1", task_id="t1", steps=steps)
        plan.mark_step_completed("s1", "Done first step")
        assert plan.current_step_index == 1
        assert plan.steps[0].status == StepStatus.COMPLETED
        assert plan.steps[0].result == "Done first step"
        assert plan.status == PlanStatus.IN_PROGRESS  # not yet complete

    def test_plan_completes_when_last_step_done(self):
        steps = [Step(id="s1", description="Only step")]
        plan = Plan(id="p1", task_id="t1", steps=steps)
        plan.mark_step_completed("s1", "Finished")
        assert plan.current_step_index == 1
        assert plan.status == PlanStatus.COMPLETED

    def test_execution_result_model(self):
        result = ExecutionResult(
            step_id="s1",
            success=True,
            output="Command succeeded",
            tool_used="bash",
            duration_seconds=1.2
        )
        assert result.success is True
        assert result.tool_used == "bash"

    def test_agent_state_initial(self):
        state = AgentState()
        assert state.task is None
        assert state.current_plan is None
        assert state.is_blocked is False
        assert state.total_steps_executed == 0


class TestOneStepRule:
    """Enforce the critical 'execute ONE step' architecture rule at domain level."""

    def test_plan_starts_with_pending_steps(self):
        plan = Plan(
            id="p1",
            task_id="t1",
            steps=[Step(id="s1", description="Do something")],
        )
        assert plan.get_current_step().status == StepStatus.PENDING

    def test_marking_step_updates_state_correctly(self):
        plan = Plan(
            id="p1",
            task_id="t1",
            steps=[
                Step(id="s1", description="Step 1"),
                Step(id="s2", description="Step 2"),
            ],
        )
        plan.mark_step_completed("s1", "ok")
        assert plan.steps[0].status == StepStatus.COMPLETED
        assert plan.get_current_step().id == "s2"  # advanced


class TestAgentProtocol:
    """Basic protocol and abstract base tests."""

    def test_base_agent_is_abstract(self):
        with pytest.raises(TypeError):
            # Cannot instantiate abstract class
            BaseAgent()

    def test_agent_protocol_compliance(self):
        # Simple check that our protocol can be used for typing
        assert hasattr(AgentProtocol, "execute_next_step")
        assert hasattr(AgentProtocol, "decompose_goal")


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
