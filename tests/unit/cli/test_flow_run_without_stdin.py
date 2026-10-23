"""`flow run` with no answer on stdin leaves the session waiting, cleanly.

Found on the 2026-10-23 smoke run: plan review asked for an answer, stdin was
closed (a script, CI, a pipe), `input()` raised EOFError and the command died
with a traceback and "Aborted!". The session is left WAITING and the command
says how to resume it -- it never approves on the user's behalf.
"""

from __future__ import annotations

from click.testing import CliRunner

from cli.commands import flow as flow_cmd
from weebot.domain.models.event import WaitForUserEvent


class _Runner:
    resumed: list = []

    def __init__(self, *a, **k):
        pass

    async def run_prompt(self, prompt, session_id=None):
        yield WaitForUserEvent(question="Plan ready. Approve?")

    async def resume_session(self, session_id, answer):
        _Runner.resumed.append(answer)
        if False:
            yield None

    async def close(self):
        pass


class _Container:
    def get(self, key):
        return None


def test_closed_stdin_leaves_the_session_waiting(monkeypatch):
    _Runner.resumed = []
    monkeypatch.setattr(flow_cmd, "AgentRunner", _Runner)
    monkeypatch.setattr(flow_cmd, "_get_state_repo", lambda: None)
    monkeypatch.setattr(flow_cmd, "_get_mediator", lambda: None)
    monkeypatch.setattr(flow_cmd, "_container", _Container())
    monkeypatch.setattr(
        flow_cmd.ModelSelectionService, "create_llm_adapter", lambda self, m: object()
    )

    result = CliRunner().invoke(
        flow_cmd.flow, ["run", "do it", "--session-id", "s-1"], input=""
    )

    assert result.exit_code == 0, result.output
    assert _Runner.resumed == []
    assert "flow resume s-1" in result.output


class _TwoQuestions(_Runner):
    """Plan review, then a constraint-gate pause, then done."""

    async def resume_session(self, session_id, answer):
        _Runner.resumed.append(answer)
        if len(_Runner.resumed) == 1:
            yield WaitForUserEvent(question="Step may violate a constraint. Proceed?")


def test_every_question_on_the_way_is_asked(monkeypatch):
    """The second wait (the constraint gate, seen on the smoke run) used to end
    the command silently with the session still waiting."""
    _Runner.resumed = []
    monkeypatch.setattr(flow_cmd, "AgentRunner", _TwoQuestions)
    monkeypatch.setattr(flow_cmd, "_get_state_repo", lambda: None)
    monkeypatch.setattr(flow_cmd, "_get_mediator", lambda: None)
    monkeypatch.setattr(flow_cmd, "_container", _Container())
    monkeypatch.setattr(
        flow_cmd.ModelSelectionService, "create_llm_adapter", lambda self, m: object()
    )

    result = CliRunner().invoke(flow_cmd.flow, ["run", "do it"], input="approve\nproceed\n")

    assert result.exit_code == 0, result.output
    assert _Runner.resumed == ["approve", "proceed"]
