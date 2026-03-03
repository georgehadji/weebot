"""Tests for WorkflowOrchestrator implementation.

Phase 2 Deliverable: 12+ tests for WorkflowOrchestrator
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.core.workflow_orchestrator import (
    WorkflowOrchestrator,
    WorkflowResult,
    TaskResult,
    TaskStatus,
)
from weebot.core.circuit_breaker import CircuitBreaker, BreakerState
from weebot.core.agent_context import AgentContext, EventBroker


class TestWorkflowOrchestratorBasics:
    """Basic initialization and configuration tests."""

    def test_default_initialization(self):
        """Orchestrator initializes with defaults."""
        orch = WorkflowOrchestrator()
        
        assert orch.max_parallel_agents == 4
        assert orch.timeout_per_task == 300

    def test_custom_initialization(self):
        """Orchestrator accepts custom parameters."""
        orch = WorkflowOrchestrator(
            max_parallel_agents=2,
            timeout_per_task=60
        )
        
        assert orch.max_parallel_agents == 2
        assert orch.timeout_per_task == 60

    def test_parallel_limit_bounds(self):
        """Parallel agents is bounded 1-10."""
        orch_low = WorkflowOrchestrator(max_parallel_agents=0)
        assert orch_low.max_parallel_agents == 1
        
        orch_high = WorkflowOrchestrator(max_parallel_agents=20)
        assert orch_high.max_parallel_agents == 10


class TestWorkflowOrchestratorExecution:
    """Workflow execution tests."""

    @pytest.mark.asyncio
    async def test_execute_single_task(self):
        """Execute workflow with single task."""
        orch = WorkflowOrchestrator()
        
        result = await orch.execute({
            "task_a": {"deps": [], "agent_role": "test"}
        })
        
        assert result.success is True
        assert "task_a" in result.completed_tasks
        assert result.task_results["task_a"].status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_linear_chain(self):
        """Execute workflow with linear dependencies."""
        orch = WorkflowOrchestrator()
        
        result = await orch.execute({
            "step1": {"deps": [], "agent_role": "test"},
            "step2": {"deps": ["step1"], "agent_role": "test"},
            "step3": {"deps": ["step2"], "agent_role": "test"},
        })
        
        assert result.success is True
        assert result.completed_tasks == {"step1", "step2", "step3"}

    @pytest.mark.asyncio
    async def test_execute_diamond_pattern(self):
        """Execute workflow with diamond dependencies."""
        orch = WorkflowOrchestrator(max_parallel_agents=4)
        
        result = await orch.execute({
            "start": {"deps": [], "agent_role": "test"},
            "left": {"deps": ["start"], "agent_role": "test"},
            "right": {"deps": ["start"], "agent_role": "test"},
            "end": {"deps": ["left", "right"], "agent_role": "test"},
        })
        
        assert result.success is True
        assert len(result.completed_tasks) == 4

    @pytest.mark.asyncio
    async def test_parallel_execution_limit(self):
        """Respects max parallel agents limit."""
        running_count = 0
        max_running = 0
        
        async def slow_handler(task_id, config, ctx):
            nonlocal running_count, max_running
            running_count += 1
            max_running = max(max_running, running_count)
            await asyncio.sleep(0.1)
            running_count -= 1
            return "done"
        
        orch = WorkflowOrchestrator(
            max_parallel_agents=2,
            task_handler=slow_handler
        )
        
        await orch.execute({
            "t1": {"deps": []},
            "t2": {"deps": []},
            "t3": {"deps": []},
            "t4": {"deps": []},
        })
        
        assert max_running <= 2


class TestWorkflowOrchestratorFailures:
    """Failure handling tests."""

    @pytest.mark.asyncio
    async def test_task_failure_handling(self):
        """Failed task is recorded correctly."""
        async def failing_handler(task_id, config, ctx):
            raise ValueError("Task failed")
        
        orch = WorkflowOrchestrator(task_handler=failing_handler)
        
        result = await orch.execute({
            "task_a": {"deps": []}
        })
        
        assert result.success is False
        assert "task_a" in result.failed_tasks
        assert result.task_results["task_a"].status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_task_timeout(self):
        """Task timeout is handled correctly."""
        async def slow_handler(task_id, config, ctx):
            await asyncio.sleep(10)  # Will timeout
            return "done"
        
        orch = WorkflowOrchestrator(
            timeout_per_task=0.1,
            task_handler=slow_handler
        )
        
        result = await orch.execute({
            "task_a": {"deps": []}
        })
        
        assert result.success is False
        assert "task_a" in result.failed_tasks
        assert "timeout" in result.task_results["task_a"].error.lower()

    @pytest.mark.asyncio
    async def test_circular_dependency_detection(self):
        """Circular dependencies are detected and reported."""
        orch = WorkflowOrchestrator()
        
        result = await orch.execute({
            "a": {"deps": ["b"]},
            "b": {"deps": ["a"]},
        })
        
        assert result.success is False
        assert "circular" in result.metadata.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_continue_on_failure(self):
        """Independent tasks continue after failure."""
        call_count = 0
        
        async def mixed_handler(task_id, config, ctx):
            nonlocal call_count
            call_count += 1
            if task_id == "fail_task":
                raise ValueError("Failed")
            return "success"
        
        orch = WorkflowOrchestrator(task_handler=mixed_handler)
        
        result = await orch.execute({
            "fail_task": {"deps": []},
            "independent": {"deps": []},
        })
        
        assert call_count == 2  # Both tasks attempted
        assert "fail_task" in result.failed_tasks
        assert "independent" in result.completed_tasks


class TestWorkflowOrchestratorCircuitBreaker:
    """Circuit breaker integration tests."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_open(self):
        """Circuit breaker blocks tasks when open."""
        breaker = CircuitBreaker(failure_threshold=1)
        await breaker.record_failure("entity_a")
        
        orch = WorkflowOrchestrator(circuit_breaker=breaker)
        
        result = await orch.execute({
            "task_a": {"deps": [], "entity_id": "entity_a"}
        })
        
        assert result.success is False
        assert "task_a" in result.failed_tasks
        assert "circuit breaker" in result.task_results["task_a"].error.lower()

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_success(self):
        """Circuit breaker records successful tasks."""
        breaker = CircuitBreaker(failure_threshold=2)
        
        async def success_handler(task_id, config, ctx):
            return "success"
        
        orch = WorkflowOrchestrator(
            circuit_breaker=breaker,
            task_handler=success_handler
        )
        
        result = await orch.execute({
            "task_a": {"deps": [], "entity_id": "entity_a"}
        })
        
        assert result.success is True
        # Check breaker has recorded success
        breaker_result = await breaker.evaluate("entity_a")
        assert breaker_result.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure(self):
        """Circuit breaker records failed tasks."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        async def fail_handler(task_id, config, ctx):
            raise ValueError("fail")
        
        orch = WorkflowOrchestrator(
            circuit_breaker=breaker,
            task_handler=fail_handler
        )
        
        await orch.execute({
            "task_a": {"deps": [], "entity_id": "entity_a"}
        })
        
        # Check breaker has recorded failure
        breaker_result = await breaker.evaluate("entity_a")
        assert breaker_result.failure_count == 1


class TestWorkflowOrchestratorEvents:
    """Event publishing tests."""

    @pytest.mark.asyncio
    async def test_events_published_to_broker(self):
        """Events are published to event broker."""
        broker = MagicMock(spec=EventBroker)
        broker.publish = AsyncMock(return_value=True)
        
        orch = WorkflowOrchestrator(event_broker=broker)
        
        await orch.execute({
            "task_a": {"deps": []}
        })
        
        # Should have published workflow_started, task_started, task_completed, workflow_completed
        calls = broker.publish.call_args_list
        event_types = [call.kwargs.get("event_type") or call.args[0] for call in calls]
        
        assert "workflow_started" in event_types
        assert "task_started" in event_types
        assert "task_completed" in event_types
        assert "workflow_completed" in event_types


class TestWorkflowOrchestratorResults:
    """Result structure and metadata tests."""

    @pytest.mark.asyncio
    async def test_result_timing(self):
        """Execution timing is recorded."""
        orch = WorkflowOrchestrator()
        
        result = await orch.execute({
            "task_a": {"deps": []}
        })
        
        assert result.execution_time_ms >= 0
        assert result.task_results["task_a"].execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_task_result_metadata(self):
        """Task results include agent context."""
        orch = WorkflowOrchestrator()
        
        result = await orch.execute({
            "task_a": {"deps": [], "agent_role": "researcher"}
        })
        
        task_result = result.task_results["task_a"]
        assert task_result.agent_id is not None
        assert task_result.agent_id.startswith("agent-")

    @pytest.mark.asyncio
    async def test_shared_data_propagation(self):
        """Shared data is accessible to all tasks."""
        accessed_data = []
        
        async def data_handler(task_id, config, ctx):
            accessed_data.append(ctx.shared_data.get("test_key"))
            return "done"
        
        orch = WorkflowOrchestrator(task_handler=data_handler)
        
        await orch.execute(
            {"task_a": {"deps": []}},
            shared_data={"test_key": "shared_value"}
        )
        
        assert accessed_data == ["shared_value"]

    @pytest.mark.asyncio
    async def test_orchestrator_id_generation(self):
        """Orchestrator ID is generated if not provided."""
        orch = WorkflowOrchestrator()
        
        result = await orch.execute({
            "task_a": {"deps": []}
        })
        
        assert result.orchestrator_id is not None
        assert result.orchestrator_id.startswith("orch-")

    @pytest.mark.asyncio
    async def test_custom_orchestrator_id(self):
        """Custom orchestrator ID is used."""
        orch = WorkflowOrchestrator()
        
        result = await orch.execute(
            {"task_a": {"deps": []}},
            orchestrator_id="custom-id-123"
        )
        
        assert result.orchestrator_id == "custom-id-123"


class TestWorkflowOrchestratorCancel:
    """Cancellation tests."""

    @pytest.mark.asyncio
    async def test_cancel_stops_new_tasks(self):
        """Cancel prevents new tasks from starting."""
        orch = WorkflowOrchestrator()
        
        async def slow_handler(task_id, config, ctx):
            await asyncio.sleep(0.5)
            return "done"
        
        orch = WorkflowOrchestrator(task_handler=slow_handler)
        
        # Start execution
        exec_task = asyncio.create_task(orch.execute({
            "t1": {"deps": []},
            "t2": {"deps": ["t1"]},
        }))
        
        # Cancel soon after
        await asyncio.sleep(0.1)
        orch.cancel()
        
        result = await exec_task
        
        # May have partial completion
        assert result.success is False or len(result.completed_tasks) < 2


class TestWorkflowOrchestratorCustomHandler:
    """Custom task handler tests."""

    @pytest.mark.asyncio
    async def test_custom_task_handler(self):
        """Custom handler is called for tasks."""
        handler_calls = []
        
        async def custom_handler(task_id, config, ctx):
            handler_calls.append((task_id, config.get("agent_role")))
            return {"custom": "output"}
        
        orch = WorkflowOrchestrator(task_handler=custom_handler)
        
        result = await orch.execute({
            "task_a": {"deps": [], "agent_role": "custom_role"}
        })
        
        assert handler_calls == [("task_a", "custom_role")]
        assert result.task_results["task_a"].output == {"custom": "output"}
