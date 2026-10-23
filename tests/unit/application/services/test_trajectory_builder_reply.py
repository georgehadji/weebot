"""TrajectoryBuilder reads the analyst's reply like every other agent (plan A6/A7).

The real run of 2026-10-22 logged "Trajectory analysis LLM call failed:
Expecting value: line 1 column 1 (char 0)": an empty reply surfaced as a JSON
decode error. A fenced reply failed the same way, because the builder called
bare `json.loads` instead of the shared `extract_json_text`. The fallback
marker (`analysis_unavailable`) is covered in test_degraded_results_are_marked.
"""

from __future__ import annotations

import logging

from weebot.application.services.trajectory_builder import TrajectoryBuilder
from weebot.domain.models.event import TrajectoryScored
from weebot.domain.models.session import Session

_FENCED = '```json\n{"trajectory_text": "t", "failure_modes": ["x"], "success_patterns": []}\n```'


class _LLM:
    def __init__(self, content: str) -> None:
        self._content = content

    async def chat(self, *a, **k):
        return type("R", (), {"content": self._content})()


def _scored() -> TrajectoryScored:
    return TrajectoryScored(
        session_id="s1",
        task_id="t1",
        score=0.5,
        failure_modes=[],
        success_patterns=[],
        trajectory_summary="fallback summary",
    )


async def test_a_fenced_reply_is_parsed():
    summary = await TrajectoryBuilder(_LLM(_FENCED)).build(Session(id="s1"), _scored())
    assert summary.failure_modes == ["x"]


async def test_an_empty_reply_is_logged_as_empty(caplog):
    with caplog.at_level(logging.WARNING):
        summary = await TrajectoryBuilder(_LLM("")).build(Session(id="s1"), _scored())
    assert summary.failure_modes == ["analysis_unavailable"]
    assert "empty reply" in caplog.text
    assert "Expecting value" not in caplog.text
