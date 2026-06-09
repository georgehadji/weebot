"""Tests for Phase 6: Cross-step TrajectoryMonitor."""
import pytest

from weebot.application.services.trajectory_monitor import TrajectoryMonitor
from weebot.domain.models.trajectory import TrajectoryHealth


@pytest.fixture
def monitor():
    return TrajectoryMonitor()


# ── reset_step() preserves cross-step state ───────────────────────

def test_reset_step_clears_tool_signatures(monitor):
    """reset_step() clears per-step rolling windows."""
    monitor.diagnose(step_id="step1", tool_signature="tool_a")
    monitor.diagnose(step_id="step1", tool_signature="tool_b")
    assert len(monitor._tool_signatures) == 2

    monitor.reset_step()
    assert len(monitor._tool_signatures) == 0


def test_reset_step_preserves_consecutive_failures(monitor):
    """Cross-step failure counter is preserved across reset_step()."""
    # Simulate failed steps
    monitor.diagnose(
        step_id="step1", tool_signature="tool_a",
        tool_output="ERROR: timeout",
    )
    monitor.diagnose(
        step_id="step1", tool_signature="tool_b",
        tool_output="ERROR: crash",
    )
    assert monitor._consecutive_failed_steps == 2

    monitor.reset_step()
    assert monitor._consecutive_failed_steps == 2  # preserved


def test_reset_step_preserves_step_results(monitor):
    """_step_results is cross-step by design — not cleared."""
    monitor.diagnose(step_id="step1", step_result="some result")
    assert len(monitor._step_results) == 1

    monitor.reset_step()
    assert len(monitor._step_results) == 1  # preserved


# ── Cross-step failure detection ──────────────────────────────────

def test_cross_step_failure_triggers_at_threshold(monitor):
    """3 consecutive error-producing steps trigger TERMINAL."""
    for i in range(3):
        diag = monitor.diagnose(
            step_id=f"step{i}",
            tool_signature=f"tool_{i}",
            tool_output=f"ERROR: something failed in step {i}",
        )
        # First two should not trigger the cross-step detector
        if i < 2:
            # Could be HEALTHY or other pattern depending on other detectors
            pass

    # After 3 consecutive errors, the cross-step detector should fire
    diag = monitor.diagnose(
        step_id="step2",
        tool_signature="tool_2",
        tool_output="ERROR: systematic failure",
    )
    assert diag.health == TrajectoryHealth.TERMINAL
    assert "consecutive steps" in diag.detail


def test_non_error_resets_consecutive_counter(monitor):
    """A successful step resets the consecutive failure counter."""
    # Two failures
    monitor.diagnose(step_id="step0", tool_signature="t1", tool_output="ERROR: fail")
    monitor.diagnose(step_id="step1", tool_signature="t2", tool_output="ERROR: fail")
    assert monitor._consecutive_failed_steps == 2

    # One success
    monitor.diagnose(step_id="step2", tool_signature="t3", tool_output="SUCCESS: done")
    assert monitor._consecutive_failed_steps == 0


def test_healthy_after_recovery(monitor):
    """After an error streak is interrupted, no cross-step flag."""
    for i in range(2):
        monitor.diagnose(
            step_id=f"step{i}", tool_signature=f"t{i}",
            tool_output=f"ERROR: fail {i}",
        )
    # Success resets counter
    monitor.diagnose(step_id="step2", tool_signature="t2", tool_output="OK")
    # One more error should NOT trigger 3-consecutive
    diag = monitor.diagnose(
        step_id="step3", tool_signature="t3", tool_output="ERROR: isolated",
    )
    assert monitor._consecutive_failed_steps == 1  # Only 1, not 3
    # Should not be TERMINAL due to cross-step detector
    # (but could be other patterns, so just check health isn't TERMINAL
    # for the cross-step reason)
    assert diag.health != TrajectoryHealth.TERMINAL or "consecutive" not in diag.detail


# ── Within-step patterns still work after reset_step() ────────────

def test_repetition_detection_after_reset(monitor):
    """repetition_threshold works correctly after reset_step()."""
    monitor.reset_step()
    for i in range(4):
        diag = monitor.diagnose(
            step_id="step1", tool_signature="same_tool",
        )
    assert diag.health == TrajectoryHealth.REPEATING


def test_tool_signature_reset_allows_new_count(monitor):
    """After reset_step(), the tool signature counter starts fresh."""
    # 3 calls to same tool in step 1
    for i in range(3):
        monitor.diagnose(step_id="step1", tool_signature="tool_a")

    monitor.reset_step()

    # 3 calls in step 2 shouldn't trigger REPEATING (counter was reset)
    for i in range(3):
        diag = monitor.diagnose(step_id="step2", tool_signature="tool_a")

    # Should not trigger yet (needs 4)
    assert diag.health != TrajectoryHealth.REPEATING

    # 4th call should trigger
    diag = monitor.diagnose(step_id="step2", tool_signature="tool_a")
    assert diag.health == TrajectoryHealth.REPEATING
