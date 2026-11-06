"""The numbers eval-gated PRs attach (plan §13): usage, tool errors, edit-failure loops, and the
two suites that produce them (edit_heavy, long_context). No LLM, no network."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from weebot.application.harness.loader import TaskLoader
from weebot.application.harness.metrics import RunMetrics, UsageTally, count_tool_events
from weebot.application.harness.runner import BenchmarkRunner
from weebot.domain.models.event import LLMCallCompleted, ToolEvent, ToolStatus

EVALS = Path(__file__).resolve().parents[2] / "tasks" / "evals"


def _edit(path: str, error: bool, status=ToolStatus.CALLED) -> ToolEvent:
    return ToolEvent(
        tool_name="file_editor", function_args={"path": path}, status=status, is_error=error
    )


def test_two_failed_edits_in_a_row_on_one_file_are_one_loop():
    events = [_edit("a.py", True), _edit("a.py", True), _edit("a.py", True)]

    assert count_tool_events(events) == (3, 3, 1)


def test_a_success_or_another_file_ends_the_run():
    events = [
        _edit("a.py", True),
        _edit("b.py", True),  # other file: streak restarts at 1
        _edit("b.py", False),  # success: ends it
        _edit("b.py", True),
        _edit("b.py", True),  # a second, separate loop
    ]

    assert count_tool_events(events) == (5, 4, 1)


def test_calling_events_and_other_tools_do_not_count_as_edits():
    other = ToolEvent(tool_name="bash", status=ToolStatus.CALLED, is_error=True)
    events = [_edit("a.py", True, status=ToolStatus.CALLING), other, other]

    assert count_tool_events(events) == (2, 2, 0)


async def test_usage_is_summed_per_session_and_other_events_are_ignored():
    tally = UsageTally()
    for sid, p, c, usd in (("s1", 100, 10, 0.01), ("s1", 50, 5, 0.02), ("s2", 7, 1, 0.5)):
        await tally.on_domain_event(
            LLMCallCompleted(session_id=sid, prompt_tokens=p, completion_tokens=c, cost=usd)
        )
    await tally.on_domain_event(types.SimpleNamespace(type="something_else"))

    assert tally.of("s1") == (2, 150, 15, pytest.approx(0.03))
    assert tally.of("nobody") == (0, 0, 0, 0.0)


class _Flow:
    def __init__(self, events):
        self._events = events
        self._session = types.SimpleNamespace(events=[], status=types.SimpleNamespace(name="X"))

    async def run(self, prompt):
        for event in self._events:
            yield event


async def test_the_runner_attaches_metrics_to_the_result():
    tally = UsageTally()

    def factory(session):
        tally._usage[session.id] = [3, 300, 30, 0.25]  # what the bus would have fed in
        return _Flow([_edit("a.py", True), _edit("a.py", True)])

    runner = BenchmarkRunner(flow_factory=factory, usage=tally)
    task = TaskLoader.load_from_dir(EVALS / "long_context")

    result = await runner.run_task(task, 0)

    assert result.metrics == RunMetrics(3, 300, 30, 0.25, 2, 2, 1)
    assert result.to_dict()["metrics"]["edit_failure_loops"] == 1


async def test_a_run_without_a_tally_reports_zero_usage():
    runner = BenchmarkRunner(flow_factory=lambda s: _Flow([]))
    task = TaskLoader.load_from_dir(EVALS / "long_context")

    result = await runner.run_task(task, 0)

    assert result.metrics.total_tokens == 0 and result.metrics.cost_usd == 0.0


# ── the suites ────────────────────────────────────────────────────────────────────────────


def test_both_suites_load_with_a_scorer():
    for name in ("edit_heavy", "long_context"):
        task = TaskLoader.load_from_dir(EVALS / name)
        assert len(task.samples) == 3 and task.custom_scorer is not None


def test_the_long_context_answers_match_the_arithmetic_in_the_prompts():
    task = TaskLoader.load_from_dir(EVALS / "long_context")
    expected = [s.expected_answer for s in task.samples]

    assert expected[0] == str(sum(n * n for n in range(1, 46)))
    assert expected[1] == f"sum={sum(7 * n + 3 for n in range(1, 51))},max={7 * 50 + 3}"
    assert expected[2] == f"chunk-3={3 * 7919 % 10007},chunk-40={40 * 7919 % 10007}"


def _reply(text: str):
    event = types.SimpleNamespace(role="assistant", message=text)
    return types.SimpleNamespace(events=[event])


def test_long_context_needs_every_part_in_the_final_reply():
    task = TaskLoader.load_from_dir(EVALS / "long_context")
    expected = task.samples[2].expected_answer

    assert task.custom_scorer(_reply("chunk-3 = 3743  chunk-40=6543"), expected) == 1.0
    assert task.custom_scorer(_reply("chunk-3=3743"), expected) == 0.0
    assert task.custom_scorer(types.SimpleNamespace(events=[]), expected) == 0.0


def test_edit_heavy_scores_the_files_on_disk(tmp_path, monkeypatch):
    task = TaskLoader.load_from_dir(EVALS / "edit_heavy")
    monkeypatch.chdir(tmp_path)
    expected = task.samples[2].expected_answer
    target = tmp_path / json.loads(expected)["dir"] / "net.py"
    target.parent.mkdir(parents=True)
    good = (
        "TIMEOUT = 60\n"
        "def fetch(u): return request(u, retries=5)\n"
        "def push(u): return request(u, retries=5)\n"
        "def request(u, retries): pass\n"
    )
    target.write_text(good, encoding="utf-8")

    assert task.custom_scorer(None, expected) == 1.0

    target.write_text(good.replace("retries=5", "retries=3", 1), encoding="utf-8")
    assert task.custom_scorer(None, expected) == 0.0  # one call site missed
    target.write_text("def (:", encoding="utf-8")
    assert task.custom_scorer(None, expected) == 0.0  # no longer parses


def test_edit_heavy_scores_zero_when_the_agent_left_nothing(tmp_path, monkeypatch):
    task = TaskLoader.load_from_dir(EVALS / "edit_heavy")
    monkeypatch.chdir(tmp_path)

    assert all(task.custom_scorer(None, s.expected_answer) == 0.0 for s in task.samples)
