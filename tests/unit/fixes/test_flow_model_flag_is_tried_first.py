"""`flow run --model X` makes X the first model each step tries.

The flag set ExecutorAgent._model, which the cascade never read: every step
used the role cascade whatever the user asked for. The pinned model now leads
the cascade, with the role models kept as fallbacks.
"""

from __future__ import annotations

import types

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.models.step_execution_context import StepExecutionContext


async def test_the_pinned_model_is_tried_first(monkeypatch):
    cascade = CascadeExecutor(llm=object(), tools=None, agent_role="executor",
                              pinned_model="vendor/pinned-model")
    tried = []

    async def _try(messages, model, *a, **k):
        tried.append(model)
        return types.SimpleNamespace(content="ok", model=model, usage=None)

    async def _no_filter(models):
        return models

    monkeypatch.setattr(cascade, "_cascade_try_chat", _try)
    monkeypatch.setattr(cascade, "get_credits_and_filter_direct", _no_filter)
    await cascade.call_with_cascade([{"role": "user", "content": "hi"}], "say hi")
    assert tried[0] == "vendor/pinned-model"


def test_the_step_context_carries_it():
    assert StepExecutionContext(pinned_model="m").executor_kwargs() == {"pinned_model": "m"}
