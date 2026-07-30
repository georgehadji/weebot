"""Harness baseline — record and compare eval outcomes across time.

``RegressionGate`` answers "is candidate config B better than baseline config A?"
by running both live. That is the right question during harness *evolution*, but
it cannot answer "is the agent worse today than it was last week" because it has
no memory: both sides are re-run every time.

This module provides the missing half — a *persisted* snapshot. Record a
baseline once, commit the artifact, and every later run is measured against it.
Without this, every harness change is unfalsifiable: a regression and an
improvement are indistinguishable.

The comparison logic is deliberately pure (no I/O, no LLM) so it is testable
without credentials. Only :func:`Baseline.save` / :func:`Baseline.load` touch
the filesystem, and only the CLI runs tasks.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA_VERSION = 1

HELD_IN = "held_in"
HELD_OUT = "held_out"


def prompt_fingerprint(prompt: str) -> str:
    """Stable short hash of a task prompt.

    Task IDs are positional (``held_in-00``), so editing ``eval_tasks.yaml``
    would silently re-point an ID at different work and make the comparison a
    lie. The fingerprint lets :func:`compare` detect that and refuse to treat
    the two as the same task.
    """
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class TaskOutcome:
    """Result of running one eval task once."""

    task_id: str
    split: str
    fingerprint: str
    passed: bool
    score: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "split": self.split,
            "fingerprint": self.fingerprint,
            "passed": self.passed,
            "score": round(self.score, 4),
        }
        if self.error:
            d["error"] = self.error
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskOutcome":
        return cls(
            task_id=d["task_id"],
            split=d.get("split", HELD_IN),
            fingerprint=d.get("fingerprint", ""),
            passed=bool(d.get("passed", False)),
            score=float(d.get("score", 0.0)),
            error=d.get("error"),
        )


def _rate(outcomes: Iterable[TaskOutcome]) -> float:
    items = list(outcomes)
    if not items:
        return 0.0
    return sum(1 for o in items if o.passed) / len(items)


@dataclass(frozen=True)
class Baseline:
    """A recorded snapshot of eval performance, committed to the repo."""

    recorded_at: str
    git_sha: str
    model: str
    harness_version: str
    outcomes: tuple[TaskOutcome, ...] = field(default_factory=tuple)
    schema_version: int = SCHEMA_VERSION
    notes: str = ""

    # ── aggregates ────────────────────────────────────────────────
    @property
    def pass_rate(self) -> float:
        return _rate(self.outcomes)

    @property
    def held_in_pass_rate(self) -> float:
        return _rate(o for o in self.outcomes if o.split == HELD_IN)

    @property
    def held_out_pass_rate(self) -> float:
        return _rate(o for o in self.outcomes if o.split == HELD_OUT)

    def by_id(self) -> dict[str, TaskOutcome]:
        return {o.task_id: o for o in self.outcomes}

    # ── serialization ─────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "recorded_at": self.recorded_at,
            "git_sha": self.git_sha,
            "model": self.model,
            "harness_version": self.harness_version,
            "notes": self.notes,
            "summary": {
                "pass_rate": round(self.pass_rate, 4),
                "held_in_pass_rate": round(self.held_in_pass_rate, 4),
                "held_out_pass_rate": round(self.held_out_pass_rate, 4),
                "total": len(self.outcomes),
                "passed": sum(1 for o in self.outcomes if o.passed),
            },
            "outcomes": [o.to_dict() for o in self.outcomes],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Baseline":
        version = int(d.get("schema_version", 0))
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"Baseline schema version {version} != expected {SCHEMA_VERSION}. "
                "Re-record the baseline."
            )
        return cls(
            recorded_at=d.get("recorded_at", ""),
            git_sha=d.get("git_sha", ""),
            model=d.get("model", ""),
            harness_version=d.get("harness_version", ""),
            notes=d.get("notes", ""),
            schema_version=version,
            outcomes=tuple(TaskOutcome.from_dict(o) for o in d.get("outcomes", [])),
        )

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | str) -> "Baseline":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"No baseline at {path}. Record one first: "
                "`python -m cli.main harness baseline record`"
            )
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class TaskDelta:
    """One task whose outcome changed between baseline and a fresh run."""

    task_id: str
    split: str
    was: bool
    now: bool

    def __str__(self) -> str:
        arrow = "PASS → FAIL" if self.was and not self.now else "FAIL → PASS"
        return f"{self.task_id} [{self.split}]: {arrow}"


@dataclass(frozen=True)
class Comparison:
    """Outcome of measuring a fresh run against a recorded baseline."""

    regressions: tuple[TaskDelta, ...]
    improvements: tuple[TaskDelta, ...]
    unchanged: int
    drifted: tuple[str, ...]
    """Task IDs whose prompt text changed — not comparable, needs re-record."""
    missing: tuple[str, ...]
    """In the baseline but absent from the fresh run."""
    added: tuple[str, ...]
    """In the fresh run but absent from the baseline."""
    baseline_pass_rate: float
    fresh_pass_rate: float
    tolerance: float

    @property
    def delta(self) -> float:
        return self.fresh_pass_rate - self.baseline_pass_rate

    @property
    def ok(self) -> bool:
        """True when the fresh run is acceptable.

        Gated on the aggregate rate rather than per-task flips: agent runs are
        stochastic, so a single flipped task is noise, while a drop in the
        overall rate is signal. Per-task flips are still reported for
        diagnosis via :attr:`regressions`.

        Drifted or missing tasks always fail — the comparison is not
        meaningful when the two runs did different work.
        """
        if self.drifted or self.missing:
            return False
        return self.delta >= -self.tolerance

    def summary(self) -> str:
        lines = [
            f"baseline {self.baseline_pass_rate:.1%} → fresh {self.fresh_pass_rate:.1%} "
            f"(Δ {self.delta:+.1%}, tolerance {self.tolerance:.1%})",
        ]
        if self.drifted:
            lines.append(
                f"  DRIFTED ({len(self.drifted)}): prompt text changed, re-record required — "
                + ", ".join(self.drifted)
            )
        if self.missing:
            lines.append(f"  MISSING ({len(self.missing)}): " + ", ".join(self.missing))
        if self.added:
            lines.append(f"  ADDED ({len(self.added)}): " + ", ".join(self.added))
        for r in self.regressions:
            lines.append(f"  REGRESSION  {r}")
        for i in self.improvements:
            lines.append(f"  improvement {i}")
        if not self.regressions and not self.improvements:
            lines.append(f"  {self.unchanged} task(s) unchanged")
        return "\n".join(lines)


def compare(
    baseline: Baseline,
    fresh: Iterable[TaskOutcome],
    tolerance: float = 0.0,
) -> Comparison:
    """Measure a fresh run against a recorded *baseline*.

    Args:
        baseline: The committed snapshot.
        fresh: Outcomes from the run being checked.
        tolerance: Allowed drop in aggregate pass rate before failing, as a
            fraction (``0.1`` permits a 10-point drop). Defaults to 0 —
            no drop tolerated.
    """
    fresh_list = list(fresh)
    base_by_id = baseline.by_id()
    fresh_by_id = {o.task_id: o for o in fresh_list}

    regressions: list[TaskDelta] = []
    improvements: list[TaskDelta] = []
    drifted: list[str] = []
    unchanged = 0

    for task_id, base in base_by_id.items():
        new = fresh_by_id.get(task_id)
        if new is None:
            continue
        # A changed prompt makes the two incomparable regardless of outcome.
        if base.fingerprint and new.fingerprint and base.fingerprint != new.fingerprint:
            drifted.append(task_id)
            continue
        if base.passed and not new.passed:
            regressions.append(TaskDelta(task_id, base.split, True, False))
        elif not base.passed and new.passed:
            improvements.append(TaskDelta(task_id, base.split, False, True))
        else:
            unchanged += 1

    missing = tuple(sorted(set(base_by_id) - set(fresh_by_id)))
    added = tuple(sorted(set(fresh_by_id) - set(base_by_id)))

    return Comparison(
        regressions=tuple(regressions),
        improvements=tuple(improvements),
        unchanged=unchanged,
        drifted=tuple(sorted(drifted)),
        missing=missing,
        added=added,
        baseline_pass_rate=baseline.pass_rate,
        fresh_pass_rate=_rate(fresh_list),
        tolerance=tolerance,
    )


def load_eval_tasks(path: Path | str) -> list[tuple[str, str, str]]:
    """Load ``eval_tasks.yaml`` into ``(task_id, split, prompt)`` triples.

    Task IDs are positional and stable as long as tasks are appended rather
    than reordered; :func:`compare` catches reordering via the fingerprint.
    """
    import yaml

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Eval tasks not found: {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    triples: list[tuple[str, str, str]] = []
    for split, key in ((HELD_IN, "held_in_tasks"), (HELD_OUT, "held_out_tasks")):
        for idx, prompt in enumerate(cfg.get(key) or []):
            triples.append((f"{split}-{idx:02d}", split, str(prompt)))
    return triples
