#!/usr/bin/env python3
"""
Weebot Multi-Agent Orchestration Demo (Phase 2)

This example demonstrates:
- WorkflowOrchestrator with DAG execution
- Circuit breaker integration
- Parallel agent execution (max 4)
- Dependency graph visualization
- Event streaming
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List

from weebot.core.workflow_orchestrator import WorkflowOrchestrator, TaskStatus
from weebot.core.circuit_breaker import CircuitBreaker
from weebot.core.dependency_graph import DependencyGraph
from weebot.core.agent_context import AgentContext, EventBroker


# =============================================================================
# Demo Task Handler - Simulates Agent Execution
# =============================================================================

@dataclass
class SimulatedAgent:
    """Simulates an agent with different capabilities."""
    role: str
    delay: float = 0.1
    fail_rate: int = 0  # Percentage chance of failure


class AgentPool:
    """Pool of simulated agents for demo."""
    
    def __init__(self):
        self._agents = {
            "researcher": SimulatedAgent("researcher", delay=0.2),
            "analyst": SimulatedAgent("analyst", delay=0.3),
            "writer": SimulatedAgent("writer", delay=0.25),
            "reviewer": SimulatedAgent("reviewer", delay=0.15),
        }
        self._execution_log: List[Dict] = []
    
    async def execute(
        self,
        task_id: str,
        config: Dict[str, Any],
        context: AgentContext
    ) -> Dict[str, Any]:
        """Execute a task with a simulated agent."""
        role = config.get("agent_role", "default")
        prompt = config.get("prompt", "")
        agent = self._agents.get(role, SimulatedAgent(role))
        
        # Simulate processing time
        await asyncio.sleep(agent.delay)
        
        # Log execution
        self._execution_log.append({
            "task_id": task_id,
            "agent": role,
            "prompt": prompt[:50] + "..." if len(prompt) > 50 else prompt,
            "context": context.agent_id,
        })
        
        # Generate result based on role
        results = {
            "researcher": {"data": f"Research data for {task_id}", "sources": 5},
            "analyst": {"insights": f"Analysis of {task_id}", "confidence": 0.92},
            "writer": {"content": f"Draft content for {task_id}", "word_count": 250},
            "reviewer": {"feedback": f"Review of {task_id}", "score": 8.5},
        }
        
        return {
            "task_id": task_id,
            "agent_role": role,
            "result": results.get(role, {"output": "completed"}),
        }


# =============================================================================
# Demo Scenarios
# =============================================================================

async def demo_linear_workflow():
    """Demo: Simple linear workflow."""
    print("\n" + "=" * 60)
    print("DEMO 1: Linear Workflow (Sequential Execution)")
    print("=" * 60)
    
    agent_pool = AgentPool()
    orchestrator = WorkflowOrchestrator(
        max_parallel_agents=4,
        timeout_per_task=10,
        task_handler=agent_pool.execute
    )
    
    # Linear chain: research → analyze → write → review
    task_graph = {
        "research": {
            "deps": [],
            "agent_role": "researcher",
            "prompt": "Research market trends for Q1 2026"
        },
        "analyze": {
            "deps": ["research"],
            "agent_role": "analyst",
            "prompt": "Analyze research findings for patterns"
        },
        "write": {
            "deps": ["analyze"],
            "agent_role": "writer",
            "prompt": "Write report based on analysis"
        },
        "review": {
            "deps": ["write"],
            "agent_role": "reviewer",
            "prompt": "Review and rate the final report"
        },
    }
    
    result = await orchestrator.execute(
        task_graph,
        orchestrator_id="linear-demo"
    )
    
    print(f"\nWorkflow: {'✓ SUCCESS' if result.success else '✗ FAILED'}")
    print(f"Execution time: {result.execution_time_ms:.1f}ms")
    print(f"Completed tasks: {len(result.completed_tasks)}")
    
    for task_id in DependencyGraph(task_graph).topological_sort():
        task_result = result.task_results[task_id]
        status_icon = "✓" if task_result.status == TaskStatus.COMPLETED else "✗"
        print(f"  {status_icon} {task_id}: {task_result.execution_time_ms:.1f}ms")


async def demo_parallel_workflow():
    """Demo: Parallel workflow with diamond pattern."""
    print("\n" + "=" * 60)
    print("DEMO 2: Parallel Workflow (Diamond Pattern)")
    print("=" * 60)
    
    agent_pool = AgentPool()
    orchestrator = WorkflowOrchestrator(
        max_parallel_agents=4,
        timeout_per_task=10,
        task_handler=agent_pool.execute
    )
    
    # Diamond pattern: start → [left, right] → end
    # left and right run in parallel!
    task_graph = {
        "start": {
            "deps": [],
            "agent_role": "researcher",
            "prompt": "Initial research phase"
        },
        "competitor_analysis": {
            "deps": ["start"],
            "agent_role": "analyst",
            "prompt": "Analyze competitors"
        },
        "market_research": {
            "deps": ["start"],
            "agent_role": "analyst",
            "prompt": "Research market size"
        },
        "synthesize": {
            "deps": ["competitor_analysis", "market_research"],
            "agent_role": "writer",
            "prompt": "Combine analyses into strategy"
        },
    }
    
    result = await orchestrator.execute(
        task_graph,
        orchestrator_id="parallel-demo"
    )
    
    print(f"\nWorkflow: {'✓ SUCCESS' if result.success else '✗ FAILED'}")
    print(f"Execution time: {result.execution_time_ms:.1f}ms")
    print(f"\nTask execution times (notice parallel tasks):")
    
    for task_id, task_result in result.task_results.items():
        print(f"  {task_id}: {task_result.execution_time_ms:.1f}ms")
    
    # Show parallel groups
    graph = DependencyGraph(task_graph)
    print("\nParallel execution groups:")
    for i, group in enumerate(graph.parallel_groups()):
        print(f"  Phase {i+1}: {', '.join(sorted(group))}")


async def demo_circuit_breaker():
    """Demo: Circuit breaker protecting failing service."""
    print("\n" + "=" * 60)
    print("DEMO 3: Circuit Breaker Protection")
    print("=" * 60)
    
    # Create circuit breaker with low threshold
    breaker = CircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=2.0,
        success_threshold=1
    )
    
    failure_count = 0
    
    async def flaky_handler(task_id: str, config: Dict, ctx: AgentContext) -> Dict:
        nonlocal failure_count
        entity_id = config.get("entity_id", task_id)
        
        # Simulate flaky external API
        if entity_id == "flaky_api":
            failure_count += 1
            if failure_count <= 2:
                raise ConnectionError(f"API timeout (failure #{failure_count})")
        
        await asyncio.sleep(0.1)
        return {"task_id": task_id, "status": "success"}
    
    orchestrator = WorkflowOrchestrator(
        max_parallel_agents=2,
        timeout_per_task=5,
        circuit_breaker=breaker,
        task_handler=flaky_handler
    )
    
    # First two calls fail, third should be blocked
    task_graph = {
        "call_1": {"deps": [], "entity_id": "flaky_api"},
        "call_2": {"deps": [], "entity_id": "flaky_api"},
        "call_3": {"deps": [], "entity_id": "flaky_api"},
    }
    
    result = await orchestrator.execute(
        task_graph,
        orchestrator_id="circuit-breaker-demo"
    )
    
    print(f"\nWorkflow: {'✓ SUCCESS' if result.success else '✗ FAILED'}")
    print(f"\nTask results:")
    for task_id, task_result in result.task_results.items():
        status = "✓" if task_result.status == TaskStatus.COMPLETED else "✗"
        error = f" ({task_result.error})" if task_result.error else ""
        print(f"  {status} {task_id}{error}")
    
    # Check circuit breaker state
    breaker_result = await breaker.evaluate("flaky_api")
    print(f"\nCircuit breaker state: {breaker_result.state.value}")
    print(f"Failure count: {breaker_result.failure_count}")


async def demo_visualization():
    """Demo: Dependency graph visualization."""
    print("\n" + "=" * 60)
    print("DEMO 4: Dependency Graph Visualization")
    print("=" * 60)
    
    # Complex workflow with multiple dependencies
    task_graph = {
        "fetch_users": {"deps": []},
        "fetch_orders": {"deps": []},
        "fetch_products": {"deps": []},
        "enrich_orders": {"deps": ["fetch_orders", "fetch_products"]},
        "user_analytics": {"deps": ["fetch_users", "enrich_orders"]},
        "generate_report": {"deps": ["user_analytics"]},
    }
    
    graph = DependencyGraph(task_graph)
    
    print("\nMermaid Diagram:")
    print("-" * 40)
    print(graph.to_mermaid())
    
    print("\n\nGraphviz DOT:")
    print("-" * 40)
    print(graph.to_graphviz())
    
    print("\n\nTopological Order:")
    print("-" * 40)
    for i, task in enumerate(graph.topological_sort(), 1):
        print(f"  {i}. {task}")
    
    print("\n\nCritical Path:")
    print("-" * 40)
    print(" -> ".join(graph.critical_path()))


async def demo_event_streaming():
    """Demo: Event streaming with EventBroker."""
    print("\n" + "=" * 60)
    print("DEMO 5: Event Streaming")
    print("=" * 60)
    
    # Simple event handler that prints events
    class PrintingEventBroker(EventBroker):
        async def publish(self, event_type: str, agent_id: str, data: Dict = None):
            print(f"  [EVENT] {event_type}: {data}")
            return True
    
    broker = PrintingEventBroker()
    
    agent_pool = AgentPool()
    orchestrator = WorkflowOrchestrator(
        max_parallel_agents=2,
        timeout_per_task=10,
        event_broker=broker,
        task_handler=agent_pool.execute
    )
    
    task_graph = {
        "task_a": {"deps": [], "agent_role": "researcher"},
        "task_b": {"deps": ["task_a"], "agent_role": "analyst"},
    }
    
    print("\nWorkflow execution events:")
    result = await orchestrator.execute(
        task_graph,
        orchestrator_id="events-demo"
    )
    
    print(f"\nWorkflow completed: {result.success}")


async def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("WEEBOT MULTI-AGENT ORCHESTRATION DEMO")
    print("Phase 2 Deliverable Showcase")
    print("=" * 60)
    
    await demo_linear_workflow()
    await demo_parallel_workflow()
    await demo_circuit_breaker()
    await demo_visualization()
    await demo_event_streaming()
    
    print("\n" + "=" * 60)
    print("All demos completed!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
