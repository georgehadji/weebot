"""A resumed web session runs the flow with the user's answer (found in plan B2c).

Two defects stopped every web resume: the composer's WAITING strategy
(`dispatch_session_input._resume`) only stored the answer and set RUNNING,
so no flow ran, and `TaskRunner.resume_session`, which does start a flow,
ran it with `context["last_prompt"]` (the original task), so FlowRouter would
have read the task text as a plan-change request instead of "approve".
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.event import DoneEvent
from weebot.domain.models.session import Session, SessionStatus


class _Flow:
    def __init__(self, prompts: list[str]) -> None:
        self._prompts = prompts

    async def run(self, prompt: str):
        self._prompts.append(prompt)
        yield DoneEvent()

    def is_done(self) -> bool:
        return True

    async def teardown(self) -> None:
        pass


async def test_resume_runs_the_flow_with_the_answer_not_the_task():
    session = Session(
        id="s1", user_id="u", agent_id="a", status=SessionStatus.WAITING,
        context={"last_prompt": "the original task"},
    )
    state_repo = AsyncMock()
    state_repo.load_session = AsyncMock(return_value=session)
    state_repo.save_session = AsyncMock()
    runner = TaskRunner(state_repo=state_repo, event_bus=AsyncMock())
    prompts: list[str] = []

    await runner.resume_session("s1", "approve", lambda s: _Flow(prompts))
    task = runner._tasks.get("s1")
    if task is not None:
        await asyncio.wait_for(task, timeout=5)

    assert prompts == ["approve"]
