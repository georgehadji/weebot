"""Weebot Core - Multi-Agent Orchestration Engine.

Phase 2 Components:
- WorkflowOrchestrator: DAG-based multi-agent execution
- CircuitBreaker: Fault tolerance with CLOSED/OPEN/HALF_OPEN states  
- DependencyGraph: DAG validation, cycle detection, topological sort
- AgentContext: Shared context for agent hierarchies
- EventBroker: Async event streaming
"""
from weebot.core.workflow_orchestrator import (
    WorkflowOrchestrator,
    WorkflowResult,
    TaskResult,
    TaskStatus,
    TaskHandler,
)
from weebot.core.circuit_breaker import (
    CircuitBreaker,
    BreakerState,
    BreakerResult,
)
from weebot.core.dependency_graph import (
    DependencyGraph,
    TaskNode,
    CircularDependencyError,
)
from weebot.core.agent_context import (
    AgentContext,
    EventBroker,
    ActivityStream,
)

__all__ = [
    # Workflow Orchestration
    "WorkflowOrchestrator",
    "WorkflowResult", 
    "TaskResult",
    "TaskStatus",
    "TaskHandler",
    # Circuit Breaker
    "CircuitBreaker",
    "BreakerState",
    "BreakerResult",
    # Dependency Graph
    "DependencyGraph",
    "TaskNode",
    "CircularDependencyError",
    # Agent Context
    "AgentContext",
    "EventBroker",
    "ActivityStream",
]
