"""A fast-fail error (401, bad key) is recorded and skips that model for the run.

The fast-fail branch only logged, though its comment said "recorded as FAILED":
the ACR tracker never saw the failure, and the cascade kept retrying a model
whose key is wrong.
"""

from __future__ import annotations

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.models.tool_collection import ToolCollection


class _BadKeyLLM:
    async def chat(self, **_):
        raise RuntimeError("Error code: 401 - unauthorized")


async def test_the_failure_is_recorded_and_the_model_skipped(monkeypatch):
    cascade = CascadeExecutor(llm=_BadKeyLLM(), tools=ToolCollection())
    seen = []
    monkeypatch.setattr(cascade, "_record_decision", lambda **kw: seen.append(kw["outcome"]))
    assert await cascade._cascade_try_chat([{"role": "user", "content": "x"}], "v/m") is None
    assert [o.value for o in seen] == ["failed"]
    assert "v/m" in cascade._server_error_models
