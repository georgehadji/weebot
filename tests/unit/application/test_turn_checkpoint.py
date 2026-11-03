"""The executor checkpoints before a file-changing call, never before a read (H5)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.agents.executor._turn_checkpoint import checkpoint_before_change


class _Port:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def snapshot(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("git exploded")


def _executor(port):
    return SimpleNamespace(
        _workspace_checkpoints=port, _current_session_id="s1", _current_step_id="step-3"
    )


@pytest.mark.asyncio
async def test_a_file_edit_takes_a_checkpoint_for_the_session_and_step():
    port = _Port()
    await checkpoint_before_change(
        _executor(port), "file_editor", {"command": "create", "path": "src/a.py"}
    )
    assert len(port.calls) == 1
    assert port.calls[0]["session_id"] == "s1" and port.calls[0]["turn_id"] == "step-3"
    assert port.calls[0]["reason"] == "file_editor"


@pytest.mark.asyncio
async def test_a_read_only_call_takes_none():
    port = _Port()
    await checkpoint_before_change(_executor(port), "file_editor", {"command": "view", "path": "a"})
    await checkpoint_before_change(_executor(port), "web_search", {"query": "x"})
    assert port.calls == []


@pytest.mark.asyncio
async def test_no_port_and_a_failing_port_never_block_the_call():
    await checkpoint_before_change(_executor(None), "bash", {"command": "rm -rf x"})
    await checkpoint_before_change(_executor(_Port(fail=True)), "bash", {"command": "rm -rf x"})
