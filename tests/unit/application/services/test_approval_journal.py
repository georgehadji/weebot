"""Approval outcomes reach the event store (ADR-013 "not done" list; plan B2).

Only `approval_requested` was journaled (as ToolApprovalEvent). A grant, a
refusal and an expired grant were log lines only, so the event store could not
show who allowed or refused a call.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval
from weebot.application.services import tool_approval
from weebot.application.services.tool_approval import (
    ConsoleApproval,
    DenyApproval,
    FlowPauseApproval,
    record_flow_reply,
    set_approval_journal,
)
from weebot.core.approval import ApprovalManager


class _Store:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    async def log_event(self, session_id, event_type, data, cost=0.0, model="", tokens_used=0):
        self.events.append((session_id, event_type, data))
        return len(self.events)


def _request(session_id: str = "s1") -> ToolCallApproval:
    return ToolCallApproval(
        session_id=session_id,
        tool_name="bash",
        arguments={"command": "rm x"},
        fingerprint="f" * 64,
        guard="exec_approval_policy",
        reason="confirm",
    )


@pytest.fixture
def store():
    s = _Store()
    set_approval_journal(s)
    yield s
    set_approval_journal(None)


async def _settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def test_a_deny_channel_refusal_is_journaled(store):
    assert await DenyApproval().resolve(_request()) is ApprovalOutcome.DENIED
    await _settle()
    assert [e[1] for e in store.events] == ["approval_denied"]
    assert store.events[0][2]["tool_name"] == "bash"


async def test_console_yes_and_no_are_journaled(store):
    async def _yes(_q):
        return "y"

    async def _no(_q):
        return "n"

    await ConsoleApproval(ask=_yes).resolve(_request())
    await ConsoleApproval(ask=_no).resolve(_request())
    await _settle()
    assert [e[1] for e in store.events] == ["approval_granted", "approval_denied"]


async def test_a_flow_reply_is_journaled(store):
    pending = {"tool_name": "bash", "fingerprint": "a" * 64}
    record_flow_reply("s1", pending, "yes", approve_tokens=frozenset({"yes"}))
    record_flow_reply("s1", pending, "no thanks", approve_tokens=frozenset({"yes"}))
    await _settle()
    assert [e[1] for e in store.events] == ["approval_granted", "approval_denied"]
    assert all(e[0] == "s1" for e in store.events)


async def test_an_expired_grant_is_journaled(store, monkeypatch):
    now = [0.0]
    # Built like tool_approval's own store, with the journal as its expiry hook.
    grants = ApprovalManager(
        ttl_seconds=10, clock=lambda: now[0], on_expired=tool_approval._journal_expired
    )
    monkeypatch.setattr(tool_approval, "_GRANTS", grants)
    grants.grant("s1", "f" * 64)
    now[0] = 11.0
    assert await FlowPauseApproval(grants).resolve(_request()) is ApprovalOutcome.PENDING
    await _settle()
    assert "approval_expired" in [e[1] for e in store.events]


async def test_without_a_journal_nothing_breaks():
    set_approval_journal(None)
    assert await DenyApproval().resolve(_request()) is ApprovalOutcome.DENIED
