"""Regression tests: HarnessConfig.trajectory reaches TrajectoryMonitor.

Phase 5: TrajectoryConfig thresholds (repetition_threshold, stagnation_window,
budget_hotspot_ratio, exhaustion_ratio) previously never flowed anywhere —
TrajectoryMonitor() was always constructed with its own hardcoded defaults.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from weebot.application.agents.executor import ExecutorAgent
from weebot.config.harness.schema import TrajectoryConfig


def _make_executor(trajectory_config=None) -> ExecutorAgent:
    from weebot.application.models.tool_collection import ToolCollection

    return ExecutorAgent(
        llm=MagicMock(), tools=ToolCollection(), trajectory_config=trajectory_config
    )


def test_defaults_when_no_trajectory_config_given():
    executor = _make_executor(trajectory_config=None)
    monitor = executor._trajectory_monitor
    assert monitor._repetition_threshold == 4
    assert monitor._stagnation_window == 3
    assert monitor._budget_hotspot_ratio == 0.4
    assert monitor._exhaustion_ratio == 0.9


def test_custom_trajectory_config_reaches_monitor():
    cfg = TrajectoryConfig(
        repetition_threshold=7, stagnation_window=5, budget_hotspot_ratio=0.6, exhaustion_ratio=0.75
    )
    executor = _make_executor(trajectory_config=cfg)
    monitor = executor._trajectory_monitor
    assert monitor._repetition_threshold == 7
    assert monitor._stagnation_window == 5
    assert monitor._budget_hotspot_ratio == 0.6
    assert monitor._exhaustion_ratio == 0.75
