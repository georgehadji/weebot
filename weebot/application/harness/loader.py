"""TaskLoader — loads SIA-compatible benchmark task directories.

A task directory must contain:
  task.md       — human-readable task description
  samples.json  — list of {"prompt": "...", "expected_answer": "..."} objects

Optionally:
  evaluate.py   — custom scorer: evaluate(session, expected_answer) -> float
                  Dynamically imported at load time.
"""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import List, Optional

from weebot.domain.models.benchmark_task import SamplePair, WeebotTask

logger = logging.getLogger(__name__)


class TaskLoader:
    """Loads WeebotTask objects from SIA-style task directories."""

    @staticmethod
    def load_from_dir(path: Path) -> WeebotTask:
        """Load a single task from *path*.

        Args:
            path: Directory containing task.md and samples.json.

        Returns:
            WeebotTask instance.

        Raises:
            FileNotFoundError: If task.md or samples.json is missing.
            ValueError: If samples.json is not a valid list.
        """
        path = Path(path).resolve()

        task_md = path / "task.md"
        samples_json = path / "samples.json"

        if not task_md.exists():
            raise FileNotFoundError(f"task.md not found in {path}")
        if not samples_json.exists():
            raise FileNotFoundError(f"samples.json not found in {path}")

        description = task_md.read_text(encoding="utf-8").strip()

        raw_samples = json.loads(samples_json.read_text(encoding="utf-8"))
        if not isinstance(raw_samples, list):
            raise ValueError(f"samples.json must be a JSON array in {path}")

        samples = tuple(
            SamplePair(
                prompt=s["prompt"],
                expected_answer=s.get("expected_answer"),
            )
            for s in raw_samples
        )

        custom_scorer = TaskLoader._load_scorer(path / "evaluate.py")

        return WeebotTask(
            task_id=path.name,
            description=description,
            samples=samples,
            custom_scorer=custom_scorer,
            source_dir=path,
        )

    @staticmethod
    def load_all_from_dir(root: Path) -> List[WeebotTask]:
        """Discover and load all tasks under *root*.

        Walks immediate subdirectories of *root* that contain task.md.
        Directories without task.md are silently skipped.

        Args:
            root: Parent directory to search.

        Returns:
            List of loaded WeebotTask objects (order is filesystem order).
        """
        root = Path(root).resolve()
        tasks: List[WeebotTask] = []

        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if not (child / "task.md").exists():
                continue
            try:
                tasks.append(TaskLoader.load_from_dir(child))
            except Exception as exc:
                logger.warning("Skipping task dir %s: %s", child, exc)

        return tasks

    @staticmethod
    def _load_scorer(evaluate_py: Path):
        """Dynamically import evaluate.py and return the evaluate function, or None."""
        if not evaluate_py.exists():
            return None

        try:
            spec = importlib.util.spec_from_file_location(
                f"_weebot_eval_{evaluate_py.parent.name}",
                str(evaluate_py.resolve()),
            )
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            fn = getattr(module, "evaluate", None)
            return fn
        except Exception as exc:
            logger.warning("Could not import evaluate.py from %s: %s", evaluate_py.parent, exc)
            return None
