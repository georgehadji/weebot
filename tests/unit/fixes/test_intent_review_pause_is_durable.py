"""The intent-review question is a durable pause.

Found on the 2026-10-23 smoke batch: for "Write is_prime to a file, run it for
97 and 100", intent review asked a clarifying question; the user answered and
the CLI died with "Session ... is not waiting (status: pending)". PlanningState
yielded a bare WaitForUserEvent without setting WAITING or persisting -- the
defect `user_pause.pause_for_user` exists to prevent, which the other gates use.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.event import WaitForUserEvent
from weebot.domain.models.intent_review import IntentReview, IntentVerdict
from weebot.domain.models.session import Session, SessionStatus


class _LLM:
    async def chat(self, *a, **k):
        raise AssertionError("planning must stop at the clarification")


@pytest.mark.asyncio
async def test_the_clarification_leaves_the_session_waiting_in_the_repository(monkeypatch):
    from weebot.application.cqrs.handlers import register_default_handlers
    from weebot.application.cqrs.mediator import Mediator
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.application.services.intent_review_service import IntentReviewService
    from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository
    from weebot.tools.base import ToolCollection

    async def _not_ready(self, contract):
        return IntentReview(
            verdict=IntentVerdict.NOT_READY, clarification_needed=["Which file name?"]
        )

    monkeypatch.setattr(IntentReviewService, "review", _not_ready)
    repo = InMemoryStateRepository()
    session = Session(id="s-intent")
    await repo.save_session(session)
    mediator = Mediator()
    register_default_handlers(mediator, repo, llm=_LLM())
    flow = PlanActFlow(
        llm=_LLM(), tools=ToolCollection(), session=session, mediator=mediator, state_repo=repo
    )

    waited = None
    async for event in flow.run("Write a function to a file, then run it for two inputs"):
        if isinstance(event, WaitForUserEvent):
            waited = event
            break

    assert waited is not None and "Which file name?" in waited.question
    stored = await repo.load_session("s-intent")
    assert stored.status == SessionStatus.WAITING
