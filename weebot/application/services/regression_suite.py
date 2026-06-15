"""RegressionSuite — loads and manages regression tasks from JSONL fixture files.

The regression suite is split into two sets:
- **held-in tasks:** Used to measure improvement (does the new harness do better
  on tasks it should?).  These are the primary optimisation signal.
- **held-out tasks:** Used to detect regression (does the new harness break
  something it previously handled?).  These prevent overfitting.

Each task is paired with an ``oracle`` — a deterministic checker that verifies
the agent's output.  Oracles are loaded as DSL strings from JSONL and compiled
to callables at load time.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional, Union

from weebot.domain.models.regression_task import OracleFn, RegressionTask

logger = logging.getLogger(__name__)


def _default_oracle(context: dict[str, Any]) -> bool:
    """Default oracle: pass if no error in context."""
    return not context.get("error")


# ── Built-in oracle DSL ──────────────────────────────────────────
# Each oracle is stored as a dict with one key (the oracle type) and
# one or more parameters.  The loader compiles these to callables.

_ORACLE_DISPATCH: dict[str, Callable[[dict, dict], Callable]] = {}


def _register_oracle(name: str):
    """Decorator to register an oracle constructor."""
    def _wrap(fn):
        _ORACLE_DISPATCH[name] = fn
        return fn
    return _wrap


@_register_oracle("file_exists")
def _oracle_file_exists(params: dict, _meta: dict) -> OracleFn:
    """Oracle that checks a file was created."""
    path = params["path"]

    def _check(context: dict[str, Any]) -> bool:
        return context.get("files_created", {}).get(path, False)
    return _check


@_register_oracle("stdout_contains")
def _oracle_stdout_contains(params: dict, _meta: dict) -> OracleFn:
    """Oracle that checks stdout contains a substring."""
    substring = params["substring"]

    def _check(context: dict[str, Any]) -> bool:
        stdout = context.get("stdout", "") or ""
        return substring in stdout
    return _check


@_register_oracle("test_passes")
def _oracle_test_passes(params: dict, _meta: dict) -> OracleFn:
    """Oracle that checks a specific test passed."""
    test_name = params["test_name"]

    def _check(context: dict[str, Any]) -> bool:
        test_results = context.get("test_results", {})
        return test_results.get(test_name, False)
    return _check


@_register_oracle("all_tests_pass")
def _oracle_all_tests_pass(_params: dict, _meta: dict) -> OracleFn:
    """Oracle that checks all tests passed."""
    def _check(context: dict[str, Any]) -> bool:
        test_results = context.get("test_results", {})
        if not test_results:
            return False
        return all(test_results.values())
    return _check


def _compile_oracle(oracle_spec: Union[dict, None], meta: dict) -> OracleFn:
    """Compile an oracle DSL spec to a callable.

    Args:
        oracle_spec: Dict like ``{"file_exists": {"path": "README.md"}}``
            or ``None`` (uses default oracle).
        meta: Task metadata dict (used by some oracle constructors).

    Returns:
        Callable oracle function.
    """
    if not oracle_spec:
        return _default_oracle

    for oracle_type, params in oracle_spec.items():
        constructor = _ORACLE_DISPATCH.get(oracle_type)
        if constructor:
            return constructor(params, meta)

    logger.warning("Unknown oracle type %r — falling back to default", oracle_spec)
    return _default_oracle


class RegressionSuite:
    """Manages held-in and held-out task sets for harness regression testing.

    Usage::

        suite = RegressionSuite.load(
            held_in_path="fixtures/regression/held_in.jsonl",
            held_out_path="fixtures/regression/held_out.jsonl",
        )
        all_tasks = suite.held_in + suite.held_out
    """

    def __init__(
        self,
        held_in: list[RegressionTask],
        held_out: list[RegressionTask],
    ):
        self.held_in = held_in
        self.held_out = held_out

    @classmethod
    def load(
        cls,
        held_in_path: Union[str, Path],
        held_out_path: Union[str, Path],
    ) -> "RegressionSuite":
        """Load regression suite from two JSONL fixture files.

        Each line in the JSONL file should be a JSON object with fields:
        - ``id`` (str): Task ID
        - ``prompt`` (str): Task prompt
        - ``oracle`` (dict, optional): Oracle DSL spec
        - ``expected_summary`` (str, optional)
        - ``metadata`` (dict, optional)

        Args:
            held_in_path: Path to held-in task JSONL.
            held_out_path: Path to held-out task JSONL.

        Returns:
            Loaded RegressionSuite.
        """
        return cls(
            held_in=cls._load_file(held_in_path),
            held_out=cls._load_file(held_out_path),
        )

    @classmethod
    def empty(cls) -> "RegressionSuite":
        """Create an empty regression suite (no tasks).

        Useful for tests or when regression testing is disabled.
        """
        return cls(held_in=[], held_out=[])

    @staticmethod
    def _load_file(path: Union[str, Path]) -> list[RegressionTask]:
        """Load a single JSONL file into RegressionTasks."""
        path = Path(path)
        if not path.exists():
            logger.warning("Regression suite file not found: %s — returning empty", path)
            return []

        tasks: list[RegressionTask] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping malformed line in %s: %s", path, exc)
                    continue

                oracle_spec = data.pop("oracle", None)
                task = RegressionTask(**data)
                task._oracle = _compile_oracle(oracle_spec, task.metadata)
                tasks.append(task)

        logger.info("Loaded %d tasks from %s", len(tasks), path)
        return tasks

    def held_in_ids(self) -> list[str]:
        """Return list of held-in task IDs."""
        return [t.id for t in self.held_in]

    def held_out_ids(self) -> list[str]:
        """Return list of held-out task IDs."""
        return [t.id for t in self.held_out]

    def all_ids(self) -> list[str]:
        """Return list of all task IDs."""
        return self.held_in_ids() + self.held_out_ids()

    def get_by_id(self, task_id: str) -> Optional[RegressionTask]:
        """Look up a task by ID across both sets."""
        for task in self.held_in + self.held_out:
            if task.id == task_id:
                return task
        return None

    def evaluate(self, task_id: str, context: dict[str, Any]) -> bool:
        """Evaluate a single task against its oracle.

        Args:
            task_id: Task ID to evaluate.
            context: Agent output context.

        Returns:
            True if the task passes its oracle.
        """
        task = self.get_by_id(task_id)
        if task is None:
            logger.warning("Unknown task %r — defaulting to pass", task_id)
            return True
        return task.evaluate(context).passed
