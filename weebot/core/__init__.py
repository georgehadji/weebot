"""Weebot Core - Multi-Agent Orchestration Engine.

Phase 2 Components:
- WorkflowOrchestrator: DAG-based multi-agent execution
- CircuitBreaker: Fault tolerance with CLOSED/OPEN/HALF_OPEN states  
- DependencyGraph: DAG validation, cycle detection, topological sort
- AgentContext: Shared context for agent hierarchies
- EventBroker: Async event streaming

Phase 3 Components (Optimization):
- MemoryMonitor: Memory usage tracking and management
- AdaptiveConcurrencyController: Dynamic worker scaling based on load
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
from weebot.core.memory_dedup import DedupStore
from weebot.core.agent_context import (
    AgentContext,
    EventBroker,
    ActivityStream,
)

# Optional optimization components
try:
    from weebot.core.memory_monitor import (
        MemoryMonitor,
        MemoryThresholds,
        MemoryStats,
        MemoryAwareMixin,
    )
    MEMORY_MONITOR_AVAILABLE = True
except ImportError:
    MEMORY_MONITOR_AVAILABLE = False

try:
    from weebot.core.adaptive_concurrency import (
        AdaptiveConcurrencyController,
        AdaptiveSemaphore,
        ConcurrencyLimits,
    )
    ADAPTIVE_CONCURRENCY_AVAILABLE = True
except ImportError:
    ADAPTIVE_CONCURRENCY_AVAILABLE = False

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
    # Memory
    "DedupStore",
]

# Add optional components if available
if MEMORY_MONITOR_AVAILABLE:
    __all__.extend([
        "MemoryMonitor",
        "MemoryThresholds",
        "MemoryStats",
        "MemoryAwareMixin",
    ])

if ADAPTIVE_CONCURRENCY_AVAILABLE:
    __all__.extend([
        "AdaptiveConcurrencyController",
        "AdaptiveSemaphore",
        "ConcurrencyLimits",
    ])
