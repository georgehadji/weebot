"""Dependency Graph Engine for task DAG execution.

Phase 2 Deliverable: DependencyGraph with DAG validation and cycle detection
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class TaskNode:
    """A node in the dependency graph representing a task."""
    id: str
    name: str
    dependencies: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Ensure dependencies is a set."""
        if isinstance(self.dependencies, list):
            self.dependencies = set(self.dependencies)


class CircularDependencyError(Exception):
    """Raised when a cycle is detected in the dependency graph."""
    
    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle)}")


class DependencyGraph:
    """
    DAG engine for task dependency resolution.
    
    Features:
    - DAG construction & validation
    - Cycle detection (raises CircularDependencyError)
    - Topological sorting (execution order)
    - Critical path analysis
    - Mermaid/Graphviz visualization
    
    Example:
        graph = DependencyGraph({
            "fetch": {"deps": []},
            "process": {"deps": ["fetch"]},
            "analyze": {"deps": ["process"]},
            "report": {"deps": ["analyze"]}
        })
        
        graph.validate()  # Raises if cycle detected
        order = graph.topological_sort()
        # Returns: ["fetch", "process", "analyze", "report"]
    """
    
    def __init__(self, tasks: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        Initialize dependency graph.
        
        Args:
            tasks: Dict mapping task_id -> task_config
                   task_config should have "deps" key with list of dependencies
        """
        self._nodes: Dict[str, TaskNode] = {}
        self._dependents: Dict[str, Set[str]] = defaultdict(set)
        
        if tasks:
            for task_id, config in tasks.items():
                deps = config.get("deps", [])
                metadata = {k: v for k, v in config.items() if k != "deps"}
                self.add_task(task_id, deps, metadata)
    
    def add_task(
        self,
        task_id: str,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TaskNode:
        """
        Add a task to the graph.
        
        Args:
            task_id: Unique identifier for the task
            dependencies: List of task_ids this task depends on
            metadata: Additional task configuration
            
        Returns:
            The created TaskNode
        """
        node = TaskNode(
            id=task_id,
            name=metadata.get("name", task_id) if metadata else task_id,
            dependencies=set(dependencies or []),
            metadata=metadata or {}
        )
        
        self._nodes[task_id] = node
        
        # Update reverse mapping (dependents)
        for dep in node.dependencies:
            self._dependents[dep].add(task_id)
        
        return node
    
    def remove_task(self, task_id: str) -> None:
        """Remove a task and its connections from the graph."""
        if task_id not in self._nodes:
            return
        
        node = self._nodes[task_id]
        
        # Remove from dependencies' dependents
        for dep in node.dependencies:
            if dep in self._dependents:
                self._dependents[dep].discard(task_id)
        
        # Remove from dependents' dependencies
        for dependent in self._dependents.get(task_id, set()):
            if dependent in self._nodes:
                self._nodes[dependent].dependencies.discard(task_id)
        
        # Clean up
        del self._nodes[task_id]
        if task_id in self._dependents:
            del self._dependents[task_id]
    
    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """Get a task node by ID."""
        return self._nodes.get(task_id)
    
    def get_dependencies(self, task_id: str) -> Set[str]:
        """Get direct dependencies of a task."""
        node = self._nodes.get(task_id)
        return node.dependencies if node else set()
    
    def get_dependents(self, task_id: str) -> Set[str]:
        """Get tasks that depend on this task."""
        return self._dependents.get(task_id, set()).copy()
    
    def get_all_dependencies(self, task_id: str) -> Set[str]:
        """Get all transitive dependencies (recursive)."""
        all_deps = set()
        to_process = list(self.get_dependencies(task_id))
        
        while to_process:
            dep = to_process.pop()
            if dep not in all_deps:
                all_deps.add(dep)
                to_process.extend(self.get_dependencies(dep))
        
        return all_deps
    
    def validate(self) -> bool:
        """
        Validate the graph has no cycles.
        
        Returns:
            True if valid DAG
            
        Raises:
            CircularDependencyError: If cycle detected
        """
        # Kahn's algorithm for cycle detection
        in_degree = {task_id: len(node.dependencies) 
                     for task_id, node in self._nodes.items()}
        
        # Start with nodes having no dependencies
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        processed = 0
        
        while queue:
            current = queue.popleft()
            processed += 1
            
            # Reduce in-degree of dependents
            for dependent in self._dependents.get(current, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        if processed != len(self._nodes):
            # Find and report the cycle
            cycle = self._find_cycle()
            raise CircularDependencyError(cycle)
        
        return True
    
    def _find_cycle(self) -> List[str]:
        """Find a cycle in the graph using DFS."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self._nodes}
        parent = {}
        
        def dfs(node_id: str, path: List[str]) -> Optional[List[str]]:
            color[node_id] = GRAY
            
            for neighbor in self._nodes[node_id].dependencies:
                if neighbor not in self._nodes:
                    continue  # Skip missing dependencies
                    
                if color[neighbor] == GRAY:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]
                
                if color[neighbor] == WHITE:
                    result = dfs(neighbor, path + [neighbor])
                    if result:
                        return result
            
            color[node_id] = BLACK
            return None
        
        for task_id in self._nodes:
            if color[task_id] == WHITE:
                cycle = dfs(task_id, [task_id])
                if cycle:
                    return cycle
        
        return []
    
    def topological_sort(self) -> List[str]:
        """
        Get tasks in dependency-respecting order.
        
        Returns:
            List of task IDs in topological order
            
        Raises:
            CircularDependencyError: If cycle detected
        """
        self.validate()  # Will raise if cycle
        
        # Kahn's algorithm
        in_degree = {task_id: len(node.dependencies) 
                     for task_id, node in self._nodes.items()}
        
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        result = []
        
        while queue:
            current = queue.popleft()
            result.append(current)
            
            for dependent in self._dependents.get(current, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        return result
    
    def get_ready_tasks(self, completed: Set[str]) -> Set[str]:
        """
        Get tasks that are ready to execute (all dependencies met).
        
        Args:
            completed: Set of task IDs that have completed
            
        Returns:
            Set of task IDs ready for execution
        """
        ready = set()
        
        for task_id, node in self._nodes.items():
            if task_id in completed:
                continue
            if node.dependencies.issubset(completed):
                ready.add(task_id)
        
        return ready
    
    def critical_path(self) -> List[str]:
        """
        Find the critical path (longest dependency chain).
        
        Returns:
            List of task IDs on the critical path
        """
        if not self._nodes:
            return []
        
        # Calculate longest path to each node
        distances = {tid: 0 for tid in self._nodes}
        
        # Process in topological order
        for task_id in self.topological_sort():
            node = self._nodes[task_id]
            for dependent in self._dependents.get(task_id, set()):
                distances[dependent] = max(distances[dependent], 
                                          distances[task_id] + 1)
        
        # Find the node with maximum distance
        end_node = max(distances.keys(), key=lambda x: distances[x])
        
        # Backtrack to find the path
        path = []
        current = end_node
        
        while current:
            path.append(current)
            # Find predecessor with max distance
            deps = self._nodes[current].dependencies
            if not deps:
                break
            current = max(deps, key=lambda x: distances.get(x, 0))
        
        return list(reversed(path))
    
    def to_mermaid(self) -> str:
        """
        Generate Mermaid diagram syntax.
        
        Returns:
            Mermaid flowchart syntax
        """
        lines = ["graph TD"]
        
        for task_id, node in self._nodes.items():
            # Add node definition with name
            safe_id = task_id.replace("-", "_").replace(" ", "_")
            display_name = node.name or task_id
            lines.append(f'    {safe_id}["{display_name}"]')
            
            # Add edges
            for dep in node.dependencies:
                safe_dep = dep.replace("-", "_").replace(" ", "_")
                lines.append(f"    {safe_dep} --> {safe_id}")
        
        return "\n".join(lines)
    
    def to_graphviz(self) -> str:
        """
        Generate Graphviz DOT syntax.
        
        Returns:
            DOT format graph definition
        """
        lines = ["digraph G {"]
        lines.append('    rankdir=TB;')
        lines.append('    node [shape=box];')
        
        for task_id, node in self._nodes.items():
            display_name = node.name or task_id
            lines.append(f'    "{task_id}" [label="{display_name}"];')
            
            for dep in node.dependencies:
                lines.append(f'    "{dep}" -> "{task_id}";')
        
        lines.append("}")
        return "\n".join(lines)
    
    def parallel_groups(self) -> List[Set[str]]:
        """
        Group tasks by execution level (tasks that can run in parallel).
        
        Returns:
            List of sets, where each set contains tasks that can run concurrently
        """
        if not self._nodes:
            return []
        
        in_degree = {task_id: len(node.dependencies) 
                     for task_id, node in self._nodes.items()}
        
        groups = []
        remaining = set(self._nodes.keys())
        
        while remaining:
            # Find all tasks with no remaining dependencies
            ready = {tid for tid in remaining if in_degree[tid] == 0}
            
            if not ready:
                # Should not happen if no cycles
                break
            
            groups.append(ready)
            remaining -= ready
            
            # Reduce in-degree of dependents
            for task_id in ready:
                for dependent in self._dependents.get(task_id, set()):
                    in_degree[dependent] -= 1
        
        return groups
    
    def is_parallelizable(self, task_a: str, task_b: str) -> bool:
        """
        Check if two tasks can run in parallel (no dependency between them).
        
        Args:
            task_a: First task ID
            task_b: Second task ID
            
        Returns:
            True if tasks can run concurrently
        """
        if task_a not in self._nodes or task_b not in self._nodes:
            return False
        
        # Check if a depends on b or b depends on a
        deps_a = self.get_all_dependencies(task_a)
        deps_b = self.get_all_dependencies(task_b)
        
        return task_a not in deps_b and task_b not in deps_a
    
    def __len__(self) -> int:
        """Return number of tasks in graph."""
        return len(self._nodes)
    
    def __contains__(self, task_id: str) -> bool:
        """Check if task exists in graph."""
        return task_id in self._nodes
    
    def __iter__(self):
        """Iterate over task IDs."""
        return iter(self._nodes.keys())
