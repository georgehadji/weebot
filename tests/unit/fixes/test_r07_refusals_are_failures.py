"""R07 (audit 2026-10-29): a refusal is a failed step, not "Step completed".

``follow_up_like`` lumped "I cannot ..." with "ok" and "sure", and the executor replaced
every such reply with "Step completed. Continuing to the next plan step.", so a step the
model could not do ended COMPLETED and the model's reason was lost. Prefixes also matched
inside words ("ok" matched "Okta ...").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.agents.executor._error_handler import ReplyKind, classify_reply
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import MessageEvent, StepEvent, StepStatus
from weebot.domain.models.plan import Plan, Step


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("", ReplyKind.FILLER),
        ("ok", ReplyKind.FILLER),
        ("Sure, I will look into that next.", ReplyKind.FILLER),
        ("Let me check the folder contents first.", ReplyKind.FILLER),
        ("I cannot read the file, permission denied.", ReplyKind.REFUSAL),
        ("I can't access that URL from here, it returns 403.", ReplyKind.REFUSAL),
        ("I'm unable to open the spreadsheet you named.", ReplyKind.REFUSAL),
        ("I don't have access to your calendar account.", ReplyKind.REFUSAL),
        ("Okta is the identity provider this tenant uses.", ReplyKind.ANSWER),
        ("Surely the config lives in settings.py, line 40.", ReplyKind.ANSWER),
        ("The report has 12 rows and the total is 4,310 EUR.", ReplyKind.ANSWER),
    ],
)
def test_reply_kinds(text, kind):
    assert classify_reply(text) is kind


@dataclass
class _Reply:
    content: str
    tool_calls: list = field(default_factory=list)


async def _run_step(reply: str) -> list:
    executor = ExecutorAgent(llm=MagicMock(), tools=ToolCollection())

    async def _cascade(messages, description):
        return _Reply(reply)

    executor._cascade.call_with_cascade = _cascade
    step = Step(id="s1", description="read the report")
    return [e async for e in executor.execute_step(Plan(title="t", steps=[step]), step)]


@pytest.mark.asyncio
async def test_a_refusal_fails_the_step_and_keeps_the_reason():
    events = await _run_step("I cannot read the file, permission denied.")
    statuses = [e.status for e in events if isinstance(e, StepEvent) and e.step_id == "s1"]
    assert statuses[-1] == StepStatus.FAILED
    messages = [e.message for e in events if isinstance(e, MessageEvent)]
    assert any("permission denied" in m for m in messages)
    assert not any(m.startswith("Step completed") for m in messages)


@pytest.mark.asyncio
async def test_an_answer_still_completes():
    events = await _run_step("The report has 12 rows and the total is 4,310 EUR.")
    statuses = [e.status for e in events if isinstance(e, StepEvent) and e.step_id == "s1"]
    assert statuses[-1] == StepStatus.COMPLETED
