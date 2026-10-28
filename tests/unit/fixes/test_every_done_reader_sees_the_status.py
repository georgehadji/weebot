"""Every reader of the closing event tells a failed run from one that worked.

Found by review of the de5d0990 fixes: ``DoneEvent.status`` reached the web UI only. The
CLI still printed a green "Done", the Windows toast said "Task completed successfully.",
the SSE stream dropped the status, and ``scripts/auto_execute.py`` printed "Flow
completed successfully" for a run whose steps failed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from weebot.domain.models.event import DoneEvent
from weebot.interfaces.cli.event_logger import _format_event
from weebot.interfaces.sse_event_subscriber import SSEEventSubscriber
from weebot.interfaces.windows_toast_subscriber import WindowsToastSubscriber

FAILED = DoneEvent(status="failed")


def test_the_cli_does_not_call_a_failed_run_done():
    text = _format_event(FAILED)
    assert "fail" in text.lower() and "green" not in text


def test_the_cli_still_says_done_for_a_run_that_worked():
    assert "Done" in _format_event(DoneEvent(status="completed"))


async def test_the_toast_does_not_report_success_for_a_failed_run():
    sent = []

    class _Channel:
        async def send(self, notification):
            sent.append(notification)

    await WindowsToastSubscriber(channel=_Channel()).on_event(FAILED)
    assert "success" not in sent[0].message.lower()
    assert sent[0].level.value == "error"


def test_the_sse_stream_carries_the_status():
    assert json.loads(SSEEventSubscriber()._serialize(FAILED))["status"] == "failed"


def test_the_auto_execute_script_names_a_failed_run():
    spec = importlib.util.spec_from_file_location("auto_execute", Path("scripts/auto_execute.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "fail" in module.done_message(FAILED).lower()
    assert "success" in module.done_message(DoneEvent(status="completed")).lower()
