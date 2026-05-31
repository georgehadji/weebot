"""Workflow Orchestrator for multi-agent DAG execution.

Phase 2 Deliverable: WorkflowOrchestrator with DAG execution and parallel agent management
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, TypeVar

from weebot.core.circuit_breaker import CircuitBreaker, BreakerState
from weebot.core.dependency_graph import (
    DependencyGraph,
    CircularDependencyError,
    MissingDependencyError,
)
from weebot.core.agent_context import AgentContext, EventBroker


class TaskStatus(Enum):
    """Status of a task in the workflow."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """Result of a task execution."""
    task_id: str
    status: TaskStatus
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    agent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    """Result of a complete workflow execution."""
    orchestrator_id: str
    success: bool
    task_results: Dict[str, TaskResult] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    completed_tasks: Set[str] = field(default_factory=set)
    failed_tasks: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


TaskHandler = Callable[[str, Dict[str, Any], AgentContext], Coroutine[Any, Any, Any]]


class WorkflowOrchestrator:
    """
    Orchestrates multi-agent workflows with DAG execution.
    
    Features:
    - DAG-based task scheduling with parallel execution
    - Max 4 parallel agents (configurable)
    - Per-task timeout handling
    - Circuit breaker integration
    - Event streaming via EventBroker
    - Graceful error handling and partial completion
    
    Example:
        orchestrator = WorkflowOrchestrator(
            max_parallel_agents=4,
            timeout_per_task=300,
            circuit_breaker=circuit_breaker
        )
        
        result = await orchestrator.execute({
            "fetch_data": {
                "deps": [],
                "agent_role": "researcher",
                "prompt": "Fetch market data"
            },
            "analyze": {
                "deps": ["fetch_data"],
                "agent_role": "analyst", 
                "prompt": "Analyze the data"
            }
        })
    """
    
    DEFAULT_MAX_PARALLEL = 4
    DEFAULT_TIMEOUT_SECONDS = 300
    
    def __init__(
        self,
        max_parallel_agents: int = DEFAULT_MAX_PARALLEL,
        timeout_per_task: float = DEFAULT_TIMEOUT_SECONDS,
        circuit_breaker: Optional[CircuitBreaker] = None,
        event_broker: Optional[EventBroker] = None,
        task_handler: Optional[TaskHandler] = None,
    ):
        """
        Initialize workflow orchestrator.
        
        Args:
            max_parallel_agents: Maximum concurrent agents (default 4)
            timeout_per_task: Timeout per task in seconds (default 300)
            circuit_breaker: Optional circuit breaker for entity protection
            event_broker: Optional event broker for streaming
            task_handler: Optional custom task handler function
        """
        self._max_parallel = max(1, min(max_parallel_agents, 10))
        self._timeout = timeout_per_task
        self._circuit_breaker = circuit_breaker
        self._event_broker = event_broker
        self._task_handler = task_handler or self._default_task_handler
        
        self._cancelled_sessions: Dict[str, bool] = {}
        self._lock = asyncio.Lock()
        
    async def execute(
        self,
        task_graph: Dict[str, Dict[str, Any]],
        orchestrator_id: Optional[str] = None,
        shared_data: Optional[Dict[str, Any]] = None
    ) -> WorkflowResult:
        """
        Execute a workflow defined by a task graph.
        
        Args:
            task_graph: Dict mapping task_id -> task_config
                       task_config must have "deps" key
                       Optional: "agent_role", "prompt", "timeout", "retries"
            orchestrator_id: Unique identifier for this workflow run
            shared_data: Initial shared data for AgentContext
            
        Returns:
            WorkflowResult with execution status and results
        """
        start_time = time.time()
        # Use local variables for execution state to support concurrent executions
        current_orch_id = orchestrator_id or f"orch-{int(start_time * 1000)}"
        current_semaphore = asyncio.Semaphore(self._max_parallel)
        
        async with self._lock:
            self._cancelled_sessions[current_orch_id] = False
        
        # Build dependency graph
        try:
            graph = DependencyGraph(task_graph)
            graph.validate()
        except MissingDependencyError as e:
            async with self._lock:
                if current_orch_id in self._cancelled_sessions:
                    del self._cancelled_sessions[current_orch_id]
            return WorkflowResult(
                orchestrator_id=current_orch_id,
                success=False,
                metadata={"error": str(e), "missing_dependencies": e.missing},
            )
        except CircularDependencyError as e:
            async with self._lock:
                if current_orch_id in self._cancelled_sessions:
                    del self._cancelled_sessions[current_orch_id]
            return WorkflowResult(
                orchestrator_id=current_orch_id,
                success=False,
                metadata={"error": f"Circular dependency: {e.cycle}"}
            )
        
        # Track task status and results
        task_status: Dict[str, TaskStatus] = {
            tid: TaskStatus.PENDING for tid in task_graph
        }
        task_results: Dict[str, TaskResult] = {}
        completed: Set[str] = set()
        failed: Set[str] = set()
        running_tasks: Dict[asyncio.Task, str] = {}
        
        # Shared context for all agents
        context = AgentContext(
            orchestrator_id=current_orch_id,
            parent_id=None,
            agent_id="orchestrator",
            nesting_level=1,
            shared_data=shared_data or {},
            event_broker=self._event_broker or EventBroker(),
        )
        
        await self._publish_event("workflow_started", {
            "orchestrator_id": current_orch_id,
            "task_count": len(task_graph)
        }, current_orch_id)
        
        # Execute tasks
        try:
            while len(completed) + len(failed) < len(task_graph):
                # Check cancellation
                async with self._lock:
                    if self._cancelled_sessions.get(current_orch_id):
                        break

                # Get tasks ready to run
                ready = graph.get_ready_tasks(completed | failed) - completed - failed
                # Avoid re-scheduling tasks already running
                ready = {tid for tid in ready if task_status.get(tid) != TaskStatus.RUNNING}

                if not ready and not running_tasks:
                    # If we reach here, no tasks are running and none can start
                    # This is a true deadlock or blocked graph state
                    break

                # Start ready tasks (up to max parallel)
                while ready and len(running_tasks) < self._max_parallel:
                    task_id = ready.pop()
                    task_config = task_graph[task_id]
                    task_status[task_id] = TaskStatus.RUNNING

                    coro = self._execute_task(
                        task_id=task_id,
                        task_config=task_config,
                        context=context,
                        task_status=task_status,
                        task_results=task_results,
                        completed=completed,
                        failed=failed,
                        semaphore=current_semaphore,
                        orch_id=current_orch_id
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
                        # CRITICAL: Await the task to ensure it has finished 
                        # its state updates (completed.add, failed.add)
                        try:
                            await task 
                        except Exception:
                            # Exceptions are handled inside _execute_task
                            pass
                else:
                    # Safety yield
                    await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            # Handle orchestration cancellation
            for tid, status in task_status.items():
                if status == TaskStatus.RUNNING:
                    task_status[tid] = TaskStatus.CANCELLED
            raise
        finally:
            is_cancelled = False
            async with self._lock:
                if current_orch_id in self._cancelled_sessions:
                    is_cancelled = self._cancelled_sessions[current_orch_id]
                    del self._cancelled_sessions[current_orch_id]

            if is_cancelled and running_tasks:
                for task, task_id in list(running_tasks.items()):
                    task.cancel()
                    task_status[task_id] = TaskStatus.CANCELLED
                    failed.add(task_id)
                if running_tasks:
                    await asyncio.gather(*running_tasks.keys(), return_exceptions=True)
                running_tasks.clear()
        
        # Build final result
        execution_time = (time.time() - start_time) * 1000
        success = len(failed) == 0 and len(completed) == len(task_graph)
        
        await self._publish_event("workflow_completed", {
            "orchestrator_id": current_orch_id,
            "success": success,
            "completed": len(completed),
            "failed": len(failed)
        }, current_orch_id)
        
        return WorkflowResult(
            orchestrator_id=current_orch_id,
            success=success,
            task_results=task_results,
            execution_time_ms=execution_time,
            completed_tasks=completed,
            failed_tasks=failed,
            metadata={
                "total_tasks": len(task_graph),
                "parallel_limit": self._max_parallel,
                "timeout_per_task": self._timeout
            }
        )
    
    async def _execute_task(
        self,
        task_id: str,
        task_config: Dict[str, Any],
        context: AgentContext,
        task_status: Dict[str, TaskStatus],
        task_results: Dict[str, TaskResult],
        completed: Set[str],
        failed: Set[str],
        semaphore: asyncio.Semaphore,
        orch_id: str
    ) -> None:
        """Execute a single task with circuit breaker and timeout protection."""
        async with semaphore:
            start_time = time.time()
            entity_id = task_config.get("entity_id", task_id)
            
            # Check circuit breaker
            if self._circuit_breaker:
                breaker_result = await self._circuit_breaker.evaluate(entity_id)
                if not breaker_result.allowed:
                    task_status[task_id] = TaskStatus.FAILED
                    failed.add(task_id)
                    task_results[task_id] = TaskResult(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        error=f"Circuit breaker open: {breaker_result.reason}",
                        execution_time_ms=0.0
                    )
                    await self._publish_event("task_blocked", {
                        "task_id": task_id,
                        "reason": breaker_result.reason
                    }, orch_id)
                    return
            
            await self._publish_event("task_started", {
                "task_id": task_id,
                "agent_role": task_config.get("agent_role")
            }, orch_id)
            
            try:
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

                # Inject recent sibling events into shared context for awareness
                recent_events = task_context.get_events_by_tag("task_completed", n=5)
                if recent_events:
                    sibling_outputs = [
                        {
                            "task_id": e.data.get("task_id"),
                            "execution_time_ms": e.data.get("execution_time_ms"),
                        }
                        for e in recent_events
                    ]
                    task_config["_sibling_outputs"] = sibling_outputs
                
                # Execute with timeout
                output = await asyncio.wait_for(
                    self._task_handler(task_id, task_config, task_context),
                    timeout=timeout
                )
                
                execution_time_ms = (time.time() - start_time) * 1000
                
                # Record success with circuit breaker
                if self._circuit_breaker:
                    await self._circuit_breaker.record_success(entity_id)
                
                task_status[task_id] = TaskStatus.COMPLETED
                completed.add(task_id)
                task_results[task_id] = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.COMPLETED,
                    output=output,
                    execution_time_ms=execution_time_ms,
                    agent_id=task_context.agent_id
                )
                
                await self._publish_event("task_completed", {
                    "task_id": task_id,
                    "execution_time_ms": execution_time_ms
                }, orch_id)
                
            except asyncio.TimeoutError:
                execution_time_ms = (time.time() - start_time) * 1000
                
                # Record failure with circuit breaker
                if self._circuit_breaker:
                    await self._circuit_breaker.record_failure(entity_id)
                
                task_status[task_id] = TaskStatus.FAILED
                failed.add(task_id)
                task_results[task_id] = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=f"Task timeout after {timeout}s",
                    execution_time_ms=execution_time_ms
                )
                
                await self._publish_event("task_failed", {
                    "task_id": task_id,
                    "error": "timeout"
                }, orch_id)
                
            except Exception as e:
                execution_time_ms = (time.time() - start_time) * 1000
                
                # Record failure with circuit breaker
                if self._circuit_breaker:
                    await self._circuit_breaker.record_failure(entity_id)
                
                task_status[task_id] = TaskStatus.FAILED
                failed.add(task_id)
                task_results[task_id] = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=str(e),
                    execution_time_ms=execution_time_ms
                )
                
                await self._publish_event("task_failed", {
                    "task_id": task_id,
                    "error": str(e)
                }, orch_id)
    
    async def _default_task_handler(
        self,
        task_id: str,
        task_config: Dict[str, Any],
        context: AgentContext
    ) -> Any:
        """
        Default task handler - simulates agent execution.
        
        Override this by providing a custom task_handler to __init__.
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
    
    async def _publish_event(self, event_type: str, data: Dict[str, Any], orch_id: Optional[str] = None) -> None:
        """Publish event to broker if available."""
        if self._event_broker:
            await self._event_broker.publish(
                event_type=event_type,
                agent_id=orch_id or self._orchestrator_id or "orchestrator",
                data=data
            )
    
    def cancel(self, orchestrator_id: Optional[str] = None) -> None:
        """
        Cancel one or all active workflow executions.
        
        Args:
            orchestrator_id: ID of the execution to cancel. If None, all are cancelled.
        """
        if orchestrator_id:
            if orchestrator_id in self._cancelled_sessions:
                self._cancelled_sessions[orchestrator_id] = True
        else:
            for oid in self._cancelled_sessions:
                self._cancelled_sessions[oid] = True
    
    @property
    def max_parallel_agents(self) -> int:
        """Get maximum parallel agents setting."""
        return self._max_parallel
    
    @property
    def timeout_per_task(self) -> float:
        """Get timeout per task setting."""
        return self._timeout
