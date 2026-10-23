"""The post-completion dream scan runs at most once per interval.

It scans recent errors across all sessions, so running it after every
completion repeated the same work. In a one-shot `flow run` the process waited
the full 10 s drain for it, then abandoned it: every run paid 10 s and an LLM
call for a result nobody kept.
"""

from __future__ import annotations

from weebot.application.flows.states import completed


def test_due_once_then_not_until_the_interval_passes(tmp_path, monkeypatch):
    marker = tmp_path / "dream_scan_last"
    monkeypatch.setattr(completed, "_DREAM_SCAN_MARKER", marker)
    assert completed._dream_scan_due(now=1000.0) is True
    assert completed._dream_scan_due(now=1000.0 + 60) is False
    assert completed._dream_scan_due(now=1000.0 + completed._DREAM_SCAN_INTERVAL_S + 1) is True
