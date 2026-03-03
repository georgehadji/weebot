"""Tests for DependencyGraph implementation.

Phase 2 Deliverable: 8+ tests for DependencyGraph
"""
from __future__ import annotations

import pytest

from weebot.core.dependency_graph import (
    DependencyGraph,
    TaskNode,
    CircularDependencyError,
)


class TestDependencyGraphBasics:
    """Basic construction and manipulation tests."""

    def test_empty_graph(self):
        """Empty graph has no nodes."""
        graph = DependencyGraph()
        assert len(graph) == 0
        assert list(graph) == []

    def test_add_single_task(self):
        """Can add a task with no dependencies."""
        graph = DependencyGraph()
        node = graph.add_task("task_a", [], {"name": "Task A"})
        
        assert len(graph) == 1
        assert "task_a" in graph
        assert graph.get_task("task_a").name == "Task A"

    def test_add_task_with_dependencies(self):
        """Can add a task with dependencies."""
        graph = DependencyGraph()
        graph.add_task("task_a")
        graph.add_task("task_b", ["task_a"])
        
        assert graph.get_dependencies("task_b") == {"task_a"}
        assert graph.get_dependents("task_a") == {"task_b"}

    def test_remove_task(self):
        """Can remove a task and its connections."""
        graph = DependencyGraph()
        graph.add_task("task_a")
        graph.add_task("task_b", ["task_a"])
        
        graph.remove_task("task_a")
        
        assert "task_a" not in graph
        assert graph.get_dependencies("task_b") == set()

    def test_task_metadata(self):
        """Task metadata is stored correctly."""
        graph = DependencyGraph()
        graph.add_task("task_a", metadata={"priority": "high", "timeout": 30})
        
        node = graph.get_task("task_a")
        assert node.metadata["priority"] == "high"
        assert node.metadata["timeout"] == 30


class TestDependencyGraphValidation:
    """Cycle detection and validation tests."""

    def test_validate_simple_dag(self):
        """Simple DAG validates successfully."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
            "c": {"deps": ["b"]},
        })
        
        assert graph.validate() is True

    def test_validate_diamond_pattern(self):
        """Diamond dependency pattern validates."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
            "c": {"deps": ["a"]},
            "d": {"deps": ["b", "c"]},
        })
        
        assert graph.validate() is True

    def test_detect_simple_cycle(self):
        """Simple A->B->A cycle is detected."""
        graph = DependencyGraph()
        graph.add_task("a", ["b"])
        graph.add_task("b", ["a"])
        
        with pytest.raises(CircularDependencyError) as exc_info:
            graph.validate()
        
        assert "a" in str(exc_info.value)
        assert "b" in str(exc_info.value)

    def test_detect_complex_cycle(self):
        """Complex multi-node cycle is detected."""
        graph = DependencyGraph()
        graph.add_task("a", ["e"])
        graph.add_task("b", ["a"])
        graph.add_task("c", ["b"])
        graph.add_task("d", ["c"])
        graph.add_task("e", ["d"])  # Creates cycle
        
        with pytest.raises(CircularDependencyError):
            graph.validate()

    def test_self_dependency_detected(self):
        """Task depending on itself is a cycle."""
        graph = DependencyGraph()
        graph.add_task("a", ["a"])
        
        with pytest.raises(CircularDependencyError):
            graph.validate()


class TestTopologicalSort:
    """Topological sorting tests."""

    def test_linear_chain_sort(self):
        """Linear chain sorts correctly."""
        graph = DependencyGraph({
            "c": {"deps": ["b"]},
            "a": {"deps": []},
            "b": {"deps": ["a"]},
        })
        
        order = graph.topological_sort()
        assert order == ["a", "b", "c"]

    def test_diamond_sort(self):
        """Diamond pattern sorts correctly."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
            "c": {"deps": ["a"]},
            "d": {"deps": ["b", "c"]},
        })
        
        order = graph.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_topological_sort_raises_on_cycle(self):
        """Sort raises error on cycle."""
        graph = DependencyGraph()
        graph.add_task("a", ["b"])
        graph.add_task("b", ["a"])
        
        with pytest.raises(CircularDependencyError):
            graph.topological_sort()

    def test_topological_sort_empty_graph(self):
        """Empty graph returns empty list."""
        graph = DependencyGraph()
        assert graph.topological_sort() == []


class TestReadyTasks:
    """Ready task computation tests."""

    def test_no_dependencies_ready(self):
        """Tasks with no deps are ready when nothing completed."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": []},
            "c": {"deps": ["a"]},
        })
        
        ready = graph.get_ready_tasks(set())
        assert ready == {"a", "b"}

    def test_dependency_completion_enables_task(self):
        """Task becomes ready when dependencies complete."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
            "c": {"deps": ["b"]},
        })
        
        ready = graph.get_ready_tasks({"a"})
        assert ready == {"b"}

    def test_all_complete_no_ready(self):
        """No tasks ready when all complete."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
        })
        
        ready = graph.get_ready_tasks({"a", "b"})
        assert ready == set()


class TestCriticalPath:
    """Critical path analysis tests."""

    def test_linear_critical_path(self):
        """Linear chain critical path is the chain itself."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
            "c": {"deps": ["b"]},
        })
        
        path = graph.critical_path()
        assert path == ["a", "b", "c"]

    def test_diamond_critical_path(self):
        """Diamond critical path is one of the parallel paths."""
        graph = DependencyGraph({
            "start": {"deps": []},
            "left": {"deps": ["start"]},
            "right": {"deps": ["start"]},
            "end": {"deps": ["left", "right"]},
        })
        
        path = graph.critical_path()
        assert path[0] == "start"
        assert path[-1] == "end"

    def test_critical_path_empty_graph(self):
        """Empty graph has empty critical path."""
        graph = DependencyGraph()
        assert graph.critical_path() == []


class TestVisualization:
    """Visualization output tests."""

    def test_to_mermaid_simple(self):
        """Mermaid output for simple graph."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
        })
        
        mermaid = graph.to_mermaid()
        assert "graph TD" in mermaid
        assert "a[" in mermaid
        assert "b[" in mermaid
        assert "a --> b" in mermaid or "a-->b" in mermaid

    def test_to_graphviz_simple(self):
        """Graphviz DOT output for simple graph."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
        })
        
        dot = graph.to_graphviz()
        assert "digraph G" in dot
        assert '"a"' in dot
        assert '"b"' in dot
        assert '"a" -> "b"' in dot

    def test_mermaid_escapes_special_chars(self):
        """Mermaid output escapes special characters."""
        graph = DependencyGraph()
        graph.add_task("task-with-dashes", [], {"name": "Task Name"})
        
        mermaid = graph.to_mermaid()
        assert "task_with_dashes" in mermaid  # Dashes replaced


class TestParallelGroups:
    """Parallel execution group tests."""

    def test_parallel_groups_linear(self):
        """Linear chain has sequential groups."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
            "c": {"deps": ["b"]},
        })
        
        groups = graph.parallel_groups()
        assert groups == [{"a"}, {"b"}, {"c"}]

    def test_parallel_groups_diamond(self):
        """Diamond has parallel middle group."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
            "c": {"deps": ["a"]},
            "d": {"deps": ["b", "c"]},
        })
        
        groups = graph.parallel_groups()
        assert groups[0] == {"a"}
        assert groups[1] == {"b", "c"}  # Parallel
        assert groups[2] == {"d"}

    def test_is_parallelizable(self):
        """Can check if two tasks can run in parallel."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": []},
            "c": {"deps": ["a"]},
        })
        
        assert graph.is_parallelizable("a", "b") is True
        assert graph.is_parallelizable("a", "c") is False


class TestTransitiveDependencies:
    """Transitive dependency tests."""

    def test_get_all_dependencies(self):
        """Get all transitive dependencies."""
        graph = DependencyGraph({
            "a": {"deps": []},
            "b": {"deps": ["a"]},
            "c": {"deps": ["b"]},
            "d": {"deps": ["c"]},
        })
        
        all_deps = graph.get_all_dependencies("d")
        assert all_deps == {"a", "b", "c"}

    def test_get_all_dependencies_empty(self):
        """Root task has no dependencies."""
        graph = DependencyGraph()
        graph.add_task("a")
        
        assert graph.get_all_dependencies("a") == set()


class TestInitializationFromDict:
    """Constructor from dict tests."""

    def test_init_from_dict(self):
        """Can initialize from task dictionary."""
        tasks = {
            "fetch": {"deps": [], "name": "Fetch Data"},
            "process": {"deps": ["fetch"], "name": "Process Data"},
            "analyze": {"deps": ["process"], "name": "Analyze"},
        }
        
        graph = DependencyGraph(tasks)
        
        assert len(graph) == 3
        assert graph.get_task("fetch").name == "Fetch Data"
        assert graph.get_dependencies("process") == {"fetch"}

    def test_init_empty_dict(self):
        """Empty dict creates empty graph."""
        graph = DependencyGraph({})
        assert len(graph) == 0
