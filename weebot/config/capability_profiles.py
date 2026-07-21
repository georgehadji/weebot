"""Capability profile registry — loads seed profiles and provides requirement maps.

Serves as the single source of truth for:
- ``ModelQualityProfile`` objects keyed by ``model_id`` (seeded from YAML)
- ``TaskRequirement`` objects keyed by ``TaskCategory`` (defining quality weights
  and hard-gate constraints per category)

This module lives in ``config/`` alongside ``model_registry.py`` and
``model_refs.py``, keeping profile data accessible without crossing layer
boundaries.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from weebot.application.services.task_model_router import TaskCategory
from weebot.domain.models.capability import (
    CapabilityAxis,
    ModelQualityProfile,
    TaskRequirement,
)

logger = logging.getLogger(__name__)

# ── Profile data file path ─────────────────────────────────────────
_PROFILES_PATH = Path(__file__).resolve().parent / "model_quality_profiles.yaml"
_BENCHMARK_PATH = Path(__file__).resolve().parent / "benchmark_results.json"

# ── In-memory cache ────────────────────────────────────────────────
_profiles_cache: dict[str, ModelQualityProfile] | None = None
_benchmark_cache: dict[str, ModelQualityProfile] | None = None


def _load_profiles() -> dict[str, ModelQualityProfile]:
    """Load seed profiles from YAML, overlaying benchmark results.

    Benchmark profiles take precedence over seed profiles for the same
    model — this allows live measurements to overwrite hand-authored seeds.
    Results are cached in memory after first load.
    """
    global _profiles_cache
    if _profiles_cache is not None:
        return _profiles_cache

    # Load seed profiles
    seeds: dict[str, ModelQualityProfile] = {}
    if _PROFILES_PATH.exists():
        try:
            with open(_PROFILES_PATH, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            for model_id, data in raw.items():
                axes_raw = data.get("axes", {})
                axes = {}
                for key, val in axes_raw.items():
                    try:
                        axis = CapabilityAxis(key)
                    except ValueError:
                        logger.warning("Unknown axis '%s' in profile for %s", key, model_id)
                        continue
                    axes[axis] = float(val)
                seeds[model_id] = ModelQualityProfile(
                    model_id=model_id,
                    axes=axes,
                    source=data.get("source", "seed"),
                )
            logger.info("Loaded %d seed profiles from %s", len(seeds), _PROFILES_PATH)
        except Exception as exc:
            logger.error("Failed to load seed profiles: %s", exc)

    # Overlay benchmark profiles (seeds → benchmarks)
    benchmarks = _load_benchmarks()
    merged = {**seeds, **benchmarks}
    logger.info(
        "Quality profiles: %d seeds + %d benchmarks = %d total",
        len(seeds), len(benchmarks), len(merged),
    )
    _profiles_cache = merged
    return merged


def get_profile(model_id: str) -> Optional[ModelQualityProfile]:
    """Return the quality profile for *model_id*, or ``None`` if not found."""
    return _load_profiles().get(model_id)


def get_all_profiles() -> dict[str, ModelQualityProfile]:
    """Return all loaded quality profiles."""
    return dict(_load_profiles())


def refresh() -> None:
    """Clear the cache so profiles are reloaded on next access (for hot-reload)."""
    global _profiles_cache, _benchmark_cache
    _profiles_cache = None
    _benchmark_cache = None


# ── Benchmark profile persistence ───────────────────────────────────

def _load_benchmarks() -> dict[str, ModelQualityProfile]:
    """Load benchmark profiles from JSON cache file."""
    global _benchmark_cache
    if _benchmark_cache is not None:
        return _benchmark_cache
    if not _BENCHMARK_PATH.exists():
        _benchmark_cache = {}
        return {}
    try:
        import json
        with open(_BENCHMARK_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        result: dict[str, ModelQualityProfile] = {}
        for model_id, data in raw.items():
            axes_raw = data.get("axes", {})
            axes = {}
            for key, val in axes_raw.items():
                try:
                    axis = CapabilityAxis(key)
                except ValueError:
                    continue
                axes[axis] = float(val)
            result[model_id] = ModelQualityProfile(
                model_id=model_id,
                axes=axes,
                source=data.get("source", "benchmark"),
            )
        _benchmark_cache = result
        return result
    except Exception as exc:
        logger.warning("Failed to load benchmark profiles: %s", exc)
        _benchmark_cache = {}
        return {}


def save_benchmark_profile(profile: ModelQualityProfile) -> None:
    """Persist a benchmark-generated profile to the JSON cache file.

    After saving, the in-memory cache is cleared so the next call to
    ``get_profile()`` picks up the new data.

    Args:
        profile: A ``ModelQualityProfile`` with ``source="benchmark"``.
    """
    import json
    benchmarks = _load_benchmarks()
    benchmarks[profile.model_id] = profile
    # Serialise to JSON
    serialised = {}
    for mid, p in benchmarks.items():
        serialised[mid] = {
            "axes": {k.value: v for k, v in p.axes.items()},
            "source": p.source,
        }
    try:
        with open(_BENCHMARK_PATH, "w", encoding="utf-8") as f:
            json.dump(serialised, f, indent=2)
        logger.info("Saved benchmark profile for %s", profile.model_id)
        # Clear cache so next load sees the update
        global _profiles_cache
        _profiles_cache = None
    except Exception as exc:
        logger.error("Failed to save benchmark profile: %s", exc)


# ── TaskCategory → TaskRequirement mapping ─────────────────────────
#
# Each TaskCategory gets a quality-weight vector and hard constraints.
# Axes not listed default to 0.0 (irrelevant for that category).

_TASK_REQUIREMENTS: dict[TaskCategory, TaskRequirement] = {
    TaskCategory.CODING: TaskRequirement(
        requires_vision=False,
        requires_tools=True,
        min_context=32000,
        quality_weights={
            CapabilityAxis.CODING: 3.0,
            CapabilityAxis.REASONING: 2.0,
            CapabilityAxis.TOOL_USE: 2.0,
            CapabilityAxis.PLANNING: 1.5,
        },
        utility_coeff={"alpha": 0.4, "beta": 0.3, "delta": 0.2, "epsilon": 0.1},
    ),
    TaskCategory.FILE_OPS: TaskRequirement(
        requires_vision=False,
        requires_tools=True,
        min_context=8000,
        quality_weights={
            CapabilityAxis.CODING: 1.0,
            CapabilityAxis.TOOL_USE: 3.0,
        },
        utility_coeff={"alpha": 0.2, "beta": 0.3, "delta": 0.3, "epsilon": 0.2},
    ),
    TaskCategory.RESEARCH: TaskRequirement(
        requires_vision=False,
        requires_tools=True,
        min_context=32000,
        quality_weights={
            CapabilityAxis.REASONING: 3.0,
            CapabilityAxis.WRITING: 2.0,
            CapabilityAxis.CITATION: 2.0,
            CapabilityAxis.LONG_CONTEXT: 2.0,
        },
        utility_coeff={"alpha": 0.3, "beta": 0.2, "delta": 0.3, "epsilon": 0.2},
    ),
    TaskCategory.BROWSER: TaskRequirement(
        requires_vision=False,
        requires_tools=True,
        min_context=16000,
        quality_weights={
            CapabilityAxis.TOOL_USE: 3.0,
            CapabilityAxis.PLANNING: 2.0,
            CapabilityAxis.CODING: 1.0,
        },
        utility_coeff={"alpha": 0.3, "beta": 0.3, "delta": 0.2, "epsilon": 0.2},
    ),
    TaskCategory.REVIEW: TaskRequirement(
        requires_vision=False,
        requires_tools=True,
        min_context=32000,
        quality_weights={
            CapabilityAxis.REASONING: 3.0,
            CapabilityAxis.CODING: 2.0,
            CapabilityAxis.PLANNING: 2.0,
        },
        utility_coeff={"alpha": 0.4, "beta": 0.3, "delta": 0.2, "epsilon": 0.1},
    ),
    TaskCategory.PLANNING: TaskRequirement(
        requires_vision=False,
        requires_tools=True,
        min_context=32000,
        quality_weights={
            CapabilityAxis.PLANNING: 3.0,
            CapabilityAxis.REASONING: 3.0,
            CapabilityAxis.WRITING: 2.0,
        },
        utility_coeff={"alpha": 0.5, "beta": 0.2, "delta": 0.2, "epsilon": 0.1},
    ),
    TaskCategory.SECURITY: TaskRequirement(
        requires_vision=False,
        requires_tools=True,
        min_context=32000,
        quality_weights={
            CapabilityAxis.REASONING: 3.0,
            CapabilityAxis.CODING: 2.0,
            CapabilityAxis.PLANNING: 2.0,
        },
        utility_coeff={"alpha": 0.4, "beta": 0.3, "delta": 0.2, "epsilon": 0.1},
    ),
    TaskCategory.SUMMARIZATION: TaskRequirement(
        requires_vision=False,
        requires_tools=False,
        min_context=64000,
        quality_weights={
            CapabilityAxis.WRITING: 3.0,
            CapabilityAxis.REASONING: 2.0,
            CapabilityAxis.LONG_CONTEXT: 2.0,
        },
        utility_coeff={"alpha": 0.3, "beta": 0.2, "delta": 0.3, "epsilon": 0.2},
    ),
    TaskCategory.GENERAL: TaskRequirement(
        requires_vision=False,
        requires_tools=True,
        min_context=16000,
        quality_weights={
            CapabilityAxis.REASONING: 1.0,
            CapabilityAxis.CODING: 1.0,
            CapabilityAxis.TOOL_USE: 1.0,
        },
        utility_coeff={"alpha": 0.3, "beta": 0.3, "delta": 0.2, "epsilon": 0.2},
    ),
}


def get_requirement(category: TaskCategory) -> TaskRequirement:
    """Return the TaskRequirement for *category*.

    Falls back to GENERAL if the category is unknown.
    """
    return _TASK_REQUIREMENTS.get(
        category,
        _TASK_REQUIREMENTS[TaskCategory.GENERAL],
    )


def get_all_requirements() -> dict[TaskCategory, TaskRequirement]:
    """Return all defined task requirements."""
    return dict(_TASK_REQUIREMENTS)
