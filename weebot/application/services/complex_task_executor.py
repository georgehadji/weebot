"""
Complex Task Executor for Weebot

This module extends the basic workflow orchestrator to handle
more complex task execution scenarios with advanced features.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, TypeVar, Union
from datetime import datetime, timedelta

from typing import TYPE_CHECKING

from weebot.core.circuit_breaker import CircuitBreaker, BreakerState
from weebot.core.dependency_graph import (
    DependencyGraph,
    CircularDependencyError,
    MissingDependencyError,
)
from weebot.core.agent_context import AgentContext, EventBroker
from weebot.core.workflow_orchestrator import (
    TaskStatus, TaskResult, WorkflowResult, TaskHandler, WorkflowOrchestrator
)

if TYPE_CHECKING:
    from weebot.application.services.strategy_adaptation import StrategyAdapter


class ComplexTaskStatus(Enum):
    """Extended status for complex tasks."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"
    WAITING_FOR_INPUT = "waiting_for_input"
    RETRYING = "retrying"
    PARTIAL_SUCCESS = "partial_success"


@dataclass
class ComplexTaskResult:
    """Enhanced result for complex task execution."""
    task_id: str
    status: ComplexTaskStatus
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    agent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    subtasks: List[TaskResult] = field(default_factory=list)
    checkpoint_data: Optional[Dict[str, Any]] = None  # For tasks that need user input


@dataclass
class ComplexWorkflowResult:
    """Enhanced result for complex workflow execution."""
    orchestrator_id: str
    success: bool
    task_results: Dict[str, ComplexTaskResult] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    completed_tasks: Set[str] = field(default_factory=set)
    failed_tasks: Set[str] = field(default_factory=set)
    suspended_tasks: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)


class RetryPolicy:
    """Defines how tasks should be retried."""
    
    def __init__(self, max_retries: int = 3, backoff_factor: float = 1.0, 
                 retryable_errors: Optional[List[str]] = None):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.retryable_errors = retryable_errors or ["timeout", "network_error", "temporarily_unavailable"]
    
    def should_retry(self, attempt: int, error: str) -> bool:
        """Determine if a task should be retried."""
        if attempt >= self.max_retries:
            return False
        
        # Check if error type is retryable
        return any(err_type.lower() in error.lower() for err_type in self.retryable_errors)
    
    async def wait_before_retry(self, attempt: int):
        """Wait before retrying with exponential backoff."""
        wait_time = self.backoff_factor * (2 ** (attempt - 1))
        await asyncio.sleep(wait_time)


class ComplexTaskExecutor:
    """
    Advanced executor for complex tasks with retry logic, checkpoints, and adaptive execution.
    """
    
    def __init__(
        self,
        max_parallel_agents: int = 4,
        timeout_per_task: float = 300,
        circuit_breaker: Optional[CircuitBreaker] = None,
        event_broker: Optional[EventBroker] = None,
        task_handler: Optional[TaskHandler] = None,
        strategy_adapter: Optional[StrategyAdapter] = None,
    ):
        """
        Initialize complex task executor.

        Args:
            max_parallel_agents: Maximum concurrent agents
            timeout_per_task: Timeout per task in seconds
            circuit_breaker: Optional circuit breaker for entity protection
            event_broker: Optional event broker for streaming
            task_handler: Optional custom task handler function
            strategy_adapter: Optional strategy adaptation system
        """
        self._max_parallel = max(1, min(max_parallel_agents, 10))
        self._timeout = timeout_per_task
        self._circuit_breaker = circuit_breaker
        self._event_broker = event_broker
        self._task_handler = task_handler or self._default_task_handler
        self._strategy_adapter = strategy_adapter

        self._orchestrator_id: Optional[str] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._cancelled = False
        self._suspended_tasks: Dict[str, Dict[str, Any]] = {}
    
    async def execute_complex_workflow(
        self,
        task_graph: Dict[str, Dict[str, Any]],
        orchestrator_id: Optional[str] = None,
        shared_data: Optional[Dict[str, Any]] = None
    ) -> ComplexWorkflowResult:
        """
        Execute a complex workflow with advanced features.

        Args:
            task_graph: Dict mapping task_id -> task_config with extended options
            orchestrator_id: Unique identifier for this workflow run
            shared_data: Initial shared data for AgentContext

        Returns:
            ComplexWorkflowResult with execution status and results
        """
        start_time = time.time()
        self._orchestrator_id = orchestrator_id or f"cx-orch-{int(start_time * 1000)}"
        self._cancelled = False

        # Initialize semaphore for parallel control
        self._semaphore = asyncio.Semaphore(self._max_parallel)

        # Build dependency graph
        try:
            graph = DependencyGraph(task_graph)
            graph.validate()
        except MissingDependencyError as e:
            return ComplexWorkflowResult(
                orchestrator_id=self._orchestrator_id,
                success=False,
                metadata={"error": str(e), "missing_dependencies": e.missing},
            )
        except CircularDependencyError as e:
            return ComplexWorkflowResult(
                orchestrator_id=self._orchestrator_id,
                success=False,
                metadata={"error": f"Circular dependency: {e.cycle}"}
            )

        # Track task status and results
        task_status: Dict[str, ComplexTaskStatus] = {
            tid: ComplexTaskStatus.PENDING for tid in task_graph
        }
        task_results: Dict[str, ComplexTaskResult] = {}
        completed: Set[str] = set()
        failed: Set[str] = set()
        suspended: Set[str] = set()
        checkpoints: List[Dict[str, Any]] = []
        running_tasks: Dict[asyncio.Task, str] = {}

        # Shared context for all agents
        context = AgentContext(
            orchestrator_id=self._orchestrator_id,
            parent_id=None,
            agent_id="orchestrator",
            nesting_level=1,
            shared_data=shared_data or {}
        )

        await self._publish_event("complex_workflow_started", {
            "orchestrator_id": self._orchestrator_id,
            "task_count": len(task_graph)
        })

        # Execute tasks
        try:
            while len(completed) + len(failed) + len(suspended) < len(task_graph) and not self._cancelled:
                # Clean up finished tasks (safety net)
                for task in list(running_tasks.keys()):
                    if task.done():
                        running_tasks.pop(task, None)

                # Get tasks ready to run
                ready = graph.get_ready_tasks((completed | failed | suspended)) - completed - failed - suspended
                # Avoid re-scheduling tasks already running
                ready = {tid for tid in ready if task_status.get(tid) in [ComplexTaskStatus.PENDING, ComplexTaskStatus.RETRYING]}

                if not ready and not running_tasks:
                    # Deadlock or all remaining tasks depend on failed/suspended tasks
                    break

                # Start ready tasks (up to max parallel)
                while ready and len(running_tasks) < self._max_parallel:
                    task_id = ready.pop()
                    task_config = task_graph[task_id]
                    task_status[task_id] = ComplexTaskStatus.RUNNING

                    coro = self._execute_complex_task(
                        task_id=task_id,
                        task_config=task_config,
                        context=context,
                        task_status=task_status,
                        task_results=task_results,
                        completed=completed,
                        failed=failed,
                        suspended=suspended,
                        checkpoints=checkpoints
                    )
                    task = asyncio.create_task(coro)
                    running_tasks[task] = task_id

                # Wait for at least one task to complete
                if running_tasks:
                    done, _pending = await asyncio.wait(
                        running_tasks.keys(),
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        running_tasks.pop(task, None)
                else:
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            # Handle orchestration cancellation
            for tid, status in task_status.items():
                if status == ComplexTaskStatus.RUNNING:
                    task_status[tid] = ComplexTaskStatus.CANCELLED
            raise
        finally:
            if self._cancelled and running_tasks:
                for task, task_id in list(running_tasks.items()):
                    task.cancel()
                    task_status[task_id] = ComplexTaskStatus.CANCELLED
                    failed.add(task_id)
                await asyncio.gather(*running_tasks.keys(), return_exceptions=True)
                running_tasks.clear()

        # Build final result
        execution_time = (time.time() - start_time) * 1000
        success = len(failed) == 0 and len(completed) == len(task_graph) - len(suspended)

        await self._publish_event("complex_workflow_completed", {
            "orchestrator_id": self._orchestrator_id,
            "success": success,
            "completed": len(completed),
            "failed": len(failed),
            "suspended": len(suspended)
        })

        return ComplexWorkflowResult(
            orchestrator_id=self._orchestrator_id,
            success=success,
            task_results=task_results,
            execution_time_ms=execution_time,
            completed_tasks=completed,
            failed_tasks=failed,
            suspended_tasks=suspended,
            checkpoints=checkpoints,
            metadata={
                "total_tasks": len(task_graph),
                "parallel_limit": self._max_parallel,
                "timeout_per_task": self._timeout
            }
        )
    
    async def _execute_complex_task(
        self,
        task_id: str,
        task_config: Dict[str, Any],
        context: AgentContext,
        task_status: Dict[str, ComplexTaskStatus],
        task_results: Dict[str, ComplexTaskResult],
        completed: Set[str],
        failed: Set[str],
        suspended: Set[str],
        checkpoints: List[Dict[str, Any]]
    ) -> None:
        """Execute a complex task with retry logic and checkpoints."""
        async with self._semaphore:
            start_time = time.time()
            entity_id = task_config.get("entity_id", task_id)
            max_retries = task_config.get("max_retries", 3)
            current_attempt = 0

            # Check circuit breaker
            if self._circuit_breaker:
                breaker_result = await self._circuit_breaker.evaluate(entity_id)
                if not breaker_result.allowed:
                    task_status[task_id] = ComplexTaskStatus.FAILED
                    failed.add(task_id)
                    task_results[task_id] = ComplexTaskResult(
                        task_id=task_id,
                        status=ComplexTaskStatus.FAILED,
                        error=f"Circuit breaker open: {breaker_result.reason}",
                        execution_time_ms=0.0
                    )
                    await self._publish_event("task_blocked", {
                        "task_id": task_id,
                        "reason": breaker_result.reason
                    })
                    return

            await self._publish_event("complex_task_started", {
                "task_id": task_id,
                "agent_role": task_config.get("agent_role")
            })

            # Prepare retry policy
            retry_policy = RetryPolicy(
                max_retries=max_retries,
                backoff_factor=task_config.get("backoff_factor", 1.0),
                retryable_errors=task_config.get("retryable_errors", ["timeout", "network_error"])
            )

            while current_attempt <= max_retries:
                current_attempt += 1
                try:
                    # Update status if retrying
                    if current_attempt > 1:
                        task_status[task_id] = ComplexTaskStatus.RETRYING
                        await self._publish_event("task_retrying", {
                            "task_id": task_id,
                            "attempt": current_attempt,
                            "max_retries": max_retries
                        })

                    # Get task-specific timeout
                    timeout = task_config.get("timeout", self._timeout)

                    # Create agent context for this task
                    task_context = AgentContext(
                        orchestrator_id=context.orchestrator_id,
                        parent_id="orchestrator",
                        agent_id=f"agent-{task_id}",
                        nesting_level=min(context.nesting_level + 1, 3),
                        shared_data=context.shared_data,
                        event_broker=context.event_broker,
                        activity_stream=context.activity_stream,
                        _data_lock=context._data_lock,
                    )

                    # Execute with timeout
                    output = await asyncio.wait_for(
                        self._execute_task_with_features(task_id, task_config, task_context),
                        timeout=timeout
                    )

                    execution_time_ms = (time.time() - start_time) * 1000

                    # Record success with circuit breaker
                    if self._circuit_breaker:
                        await self._circuit_breaker.record_success(entity_id)

                    # Check if task needs user input (checkpoint)
                    if task_config.get("requires_input"):
                        task_status[task_id] = ComplexTaskStatus.WAITING_FOR_INPUT
                        suspended.add(task_id)
                        
                        checkpoint_data = {
                            "task_id": task_id,
                            "checkpoint_id": f"chk_{task_id}_{int(time.time())}",
                            "prompt": task_config.get("input_prompt", "Continue with task?"),
                            "context": output
                        }
                        
                        checkpoints.append(checkpoint_data)
                        
                        task_results[task_id] = ComplexTaskResult(
                            task_id=task_id,
                            status=ComplexTaskStatus.WAITING_FOR_INPUT,
                            output=output,
                            execution_time_ms=execution_time_ms,
                            agent_id=task_context.agent_id,
                            checkpoint_data=checkpoint_data
                        )
                        
                        await self._publish_event("task_waiting_for_input", checkpoint_data)
                        return

                    task_status[task_id] = ComplexTaskStatus.COMPLETED
                    completed.add(task_id)
                    task_results[task_id] = ComplexTaskResult(
                        task_id=task_id,
                        status=ComplexTaskStatus.COMPLETED,
                        output=output,
                        execution_time_ms=execution_time_ms,
                        agent_id=task_context.agent_id,
                        retries=current_attempt - 1
                    )

                    await self._publish_event("complex_task_completed", {
                        "task_id": task_id,
                        "execution_time_ms": execution_time_ms,
                        "retries": current_attempt - 1
                    })
                    
                    return  # Success, exit retry loop

                except asyncio.TimeoutError:
                    execution_time_ms = (time.time() - start_time) * 1000
                    
                    if current_attempt <= max_retries and retry_policy.should_retry(current_attempt, "timeout"):
                        await retry_policy.wait_before_retry(current_attempt)
                        continue  # Retry
                    else:
                        # Record failure with circuit breaker
                        if self._circuit_breaker:
                            await self._circuit_breaker.record_failure(entity_id)

                        task_status[task_id] = ComplexTaskStatus.FAILED
                        failed.add(task_id)
                        task_results[task_id] = ComplexTaskResult(
                            task_id=task_id,
                            status=ComplexTaskStatus.FAILED,
                            error=f"Task timeout after {timeout}s, attempted {current_attempt} times",
                            execution_time_ms=execution_time_ms,
                            retries=current_attempt - 1
                        )

                        await self._publish_event("complex_task_failed", {
                            "task_id": task_id,
                            "error": "timeout",
                            "attempts": current_attempt
                        })
                        return

                except Exception as e:
                    execution_time_ms = (time.time() - start_time) * 1000
                    
                    error_msg = str(e)
                    if current_attempt <= max_retries and retry_policy.should_retry(current_attempt, error_msg):
                        await retry_policy.wait_before_retry(current_attempt)
                        continue  # Retry
                    else:
                        # Record failure with circuit breaker
                        if self._circuit_breaker:
                            await self._circuit_breaker.record_failure(entity_id)

                        task_status[task_id] = ComplexTaskStatus.FAILED
                        failed.add(task_id)
                        task_results[task_id] = ComplexTaskResult(
                            task_id=task_id,
                            status=ComplexTaskStatus.FAILED,
                            error=f"{error_msg}, attempted {current_attempt} times",
                            execution_time_ms=execution_time_ms,
                            retries=current_attempt - 1
                        )

                        await self._publish_event("complex_task_failed", {
                            "task_id": task_id,
                            "error": error_msg,
                            "attempts": current_attempt
                        })
                        return
    
    async def _execute_task_with_features(
        self,
        task_id: str,
        task_config: Dict[str, Any],
        context: AgentContext
    ) -> Any:
        """Execute a task with additional features like subtasks."""
        # Check if this task has subtasks
        subtasks_config = task_config.get("subtasks", [])
        if subtasks_config:
            # Execute subtasks sequentially or in parallel based on configuration
            subtask_results = []
            for subtask_config in subtasks_config:
                subtask_result = await self._task_handler(
                    f"{task_id}_subtask_{len(subtask_results)}",
                    subtask_config,
                    context
                )
                subtask_results.append(subtask_result)
            
            return {
                "main_task": task_config.get("prompt", ""),
                "subtask_results": subtask_results
            }
        else:
            # Execute as a regular task
            return await self._task_handler(task_id, task_config, context)
    
    async def _default_task_handler(
        self,
        task_id: str,
        task_config: Dict[str, Any],
        context: AgentContext
    ) -> Any:
        """
        Default task handler for complex tasks.

        This can be overridden by providing a custom task_handler to __init__.
        """
        agent_role = task_config.get("agent_role", "default")
        prompt = task_config.get("prompt", "")

        # Simulate processing
        await asyncio.sleep(0.01)

        return {
            "task_id": task_id,
            "agent_role": agent_role,
            "prompt_processed": prompt,
            "context_id": context.agent_id
        }

    async def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish event to broker if available."""
        if self._event_broker:
            await self._event_broker.publish(
                event_type=event_type,
                agent_id=self._orchestrator_id or "orchestrator",
                data=data
            )

    def cancel(self) -> None:
        """Cancel the workflow execution."""
        self._cancelled = True

    @property
    def max_parallel_agents(self) -> int:
        """Get maximum parallel agents setting."""
        return self._max_parallel

    @property
    def timeout_per_task(self) -> float:
        """Get timeout per task setting."""
        return self._timeout


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        # Create a complex task executor
        executor = ComplexTaskExecutor(max_parallel_agents=3)
        
        # Define a complex task graph
        complex_task_graph = {
            "task_1": {
                "deps": [],
                "agent_role": "researcher",
                "prompt": "Research AI trends",
                "max_retries": 2,
                "timeout": 60
            },
            "task_2": {
                "deps": ["task_1"],
                "agent_role": "analyst", 
                "prompt": "Analyze research findings",
                "max_retries": 3,
                "requires_input": True,
                "input_prompt": "Should I proceed with the analysis?"
            },
            "task_3": {
                "deps": ["task_2"],
                "agent_role": "writer",
                "prompt": "Write summary report",
                "subtasks": [
                    {"prompt": "Create outline", "agent_role": "planner"},
                    {"prompt": "Write introduction", "agent_role": "writer"},
                    {"prompt": "Write conclusion", "agent_role": "writer"}
                ]
            }
        }
        
        print("Executing complex workflow...")
        result = await executor.execute_complex_workflow(
            task_graph=complex_task_graph,
            orchestrator_id="test_complex_workflow"
        )
        
        print(f"Workflow completed with success: {result.success}")
        print(f"Completed tasks: {len(result.completed_tasks)}")
        print(f"Failed tasks: {len(result.failed_tasks)}")
        print(f"Suspended tasks: {len(result.suspended_tasks)}")
        print(f"Checkpoints: {len(result.checkpoints)}")
        
        for task_id, task_result in result.task_results.items():
            print(f"  {task_id}: {task_result.status.value} (retries: {task_result.retries})")
    
    # Run the example
    asyncio.run(main())