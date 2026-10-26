"""OBS-1: every log line and every LLM call can be tied to its session and step.

Plan item "Phase 6" of tasks/specs/arch_audit_2026_10_remediation_plan.md.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.strategies.llm_pool import (
    BoundedLLMAdapter,
    LLMPool,
    prompt_sha,
)
from weebot.core import log_context as lc
from weebot.domain.models.llm_response import LLMResponse

log = logging.getLogger("weebot.test.obs")


def _stamped(caplog, text: str):
    [record] = [r for r in caplog.records if text in r.getMessage()]
    return record


class TestLogContext:
    def test_a_record_inside_the_context_carries_all_three_ids(self, caplog):
        with caplog.at_level(logging.INFO):
            with lc.log_context(session_id="s-1", step_id="step-3", correlation_id="c-9"):
                log.info("inside")
            log.info("outside")
        inside, outside = _stamped(caplog, "inside"), _stamped(caplog, "outside")
        assert (inside.session_id, inside.step_id, inside.correlation_id) == ("s-1", "step-3", "c-9")
        assert (outside.session_id, outside.step_id, outside.correlation_id) == ("", "", "")

    def test_an_existing_correlation_id_is_kept_by_a_nested_context(self):
        with lc.log_context(session_id="s", correlation_id="runner-id"):
            with lc.log_context(session_id="s"):
                assert lc.current()["correlation_id"] == "runner-id"
            with lc.log_context(session_id="s", new_correlation=True):
                assert lc.current()["correlation_id"] != "runner-id"
            assert lc.current()["correlation_id"] == "runner-id"

    def test_a_flow_without_a_runner_gets_its_own_correlation_id(self):
        with lc.log_context(session_id="s"):
            assert len(lc.current()["correlation_id"]) == 12

    def test_the_structured_logger_reads_the_same_ids(self):
        from weebot.core.structured_logger import get_correlation_id

        with lc.log_context(session_id="s", correlation_id="shared"):
            assert get_correlation_id() == "shared"

    def test_bind_step_is_visible_to_later_log_lines(self, caplog):
        with caplog.at_level(logging.INFO), lc.log_context(session_id="s"):
            lc.bind_step("step-7", "s")
            log.info("in a tool")
        assert _stamped(caplog, "in a tool").step_id == "step-7"


class TestTheBindingSites:
    @pytest.mark.asyncio
    async def test_the_runner_binds_the_session_for_its_whole_run(self, caplog):
        from weebot.application.services.task_runner import TaskRunner

        repo = MagicMock()
        repo.load_session = AsyncMock(return_value=None)  # logs "not found" inside the binding
        runner = TaskRunner(state_repo=repo, event_bus=MagicMock(), task_queue=MagicMock())
        with caplog.at_level(logging.ERROR):
            await runner._run_flow("sess-runner", MagicMock(), "hello")
        record = _stamped(caplog, "not found for background run")
        assert record.session_id == "sess-runner" and record.correlation_id
        assert lc.current() == {}, "the binding must not leak past the run"

    @pytest.mark.asyncio
    async def test_the_flow_binds_its_session_and_keeps_the_runners_correlation(self, caplog):
        from weebot.application.flows.plan_act_flow import PlanActFlow

        async def states(prompt):
            log.info("inside the flow")
            yield "event"

        flow = SimpleNamespace(
            _session=SimpleNamespace(id="sess-flow"), _run_states=states, _cost_meter=None
        )
        with caplog.at_level(logging.INFO), lc.log_context(correlation_id="from-runner"):
            events = [e async for e in PlanActFlow.run(flow, "go")]
        assert events == ["event"]
        record = _stamped(caplog, "inside the flow")
        assert record.session_id == "sess-flow" and record.correlation_id == "from-runner"

    def test_a_tool_executors_step_context_binds_the_step(self, caplog):
        from weebot.application.agents.executor._tool_executor import ToolExecutor

        executor = ToolExecutor(tools=MagicMock())
        with caplog.at_level(logging.INFO), lc.log_context(session_id="s"):
            executor.set_step_context("step-2", "s", "do the thing")
            log.info("emitted by a tool")
        record = _stamped(caplog, "emitted by a tool")
        assert (record.session_id, record.step_id) == ("s", "step-2")


class _Inner:
    def __init__(self, usage=None, model="openai/gpt-4o-mini"):
        self._resp = LLMResponse(content="ok", model=model, usage=usage or {})

    async def chat(self, **kwargs):
        return self._resp

    async def build_multimodal_message(self, *a, **k):  # pragma: no cover
        return {}


class TestOneRecordPerLLMCall:
    @pytest.mark.asyncio
    async def test_a_direct_call_logs_every_field_and_publishes_completion(self, caplog):
        published = []

        async def publish(event):
            published.append(event)

        pool = LLMPool(max_concurrent=2)
        llm = BoundedLLMAdapter(
            _Inner(usage={"prompt_tokens": 120, "completion_tokens": 30}), pool, on_completed=publish
        )
        messages = [
            {"role": "system", "content": "You are the planner."},
            {"role": "user", "content": "plan it"},
        ]
        with caplog.at_level(logging.INFO), lc.log_context(session_id="sess-llm"):
            await llm.chat(messages=messages)

        text = _stamped(caplog, "llm_call").getMessage()
        for fragment in (
            "model=openai/gpt-4o-mini",
            "outcome=ok",
            "prompt_tokens=120",
            "completion_tokens=30",
            f"prompt_sha={prompt_sha(messages)}",
            "latency_ms=",
        ):
            assert fragment in text, (fragment, text)
        [event] = published
        assert (event.session_id, event.prompt_tokens, event.completion_tokens) == ("sess-llm", 120, 30)

    @pytest.mark.asyncio
    async def test_a_call_inside_the_cascades_slot_is_logged_but_not_double_counted(self):
        published = []

        async def publish(event):
            published.append(event)

        pool = LLMPool(max_concurrent=1)
        llm = BoundedLLMAdapter(_Inner(), pool, on_completed=publish)
        async with pool:  # the cascade's slot: it reports its own completion
            await llm.chat(messages=[{"role": "user", "content": "x"}])
        assert published == []

    @pytest.mark.asyncio
    async def test_a_failed_call_is_logged_with_its_outcome_and_publishes_nothing(self, caplog):
        published = []

        class Boom(_Inner):
            async def chat(self, **kwargs):
                raise RuntimeError("503")

        llm = BoundedLLMAdapter(Boom(), LLMPool(max_concurrent=1), on_completed=published.append)
        with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
            await llm.chat(messages=[{"role": "user", "content": "x"}])
        assert "outcome=error" in _stamped(caplog, "llm_call").getMessage()
        assert published == []

    @pytest.mark.asyncio
    async def test_a_broken_completion_hook_never_fails_the_call(self, caplog):
        async def broken(event):
            raise RuntimeError("bus down")

        llm = BoundedLLMAdapter(_Inner(), LLMPool(max_concurrent=1), on_completed=broken)
        with caplog.at_level(logging.WARNING):
            resp = await llm.chat(messages=[{"role": "user", "content": "x"}])
        assert resp.content == "ok"
        assert "could not record an LLM call" in caplog.text

    def test_the_prompt_sha_tracks_the_system_prompt_only(self):
        a = [{"role": "system", "content": "v1"}, {"role": "user", "content": "q1"}]
        b = [{"role": "system", "content": "v1"}, {"role": "user", "content": "q2"}]
        c = [{"role": "system", "content": "v2"}, {"role": "user", "content": "q1"}]
        assert prompt_sha(a) == prompt_sha(b) != prompt_sha(c)
        assert len(prompt_sha(a)) == 12
        assert prompt_sha([{"role": "user", "content": "q"}]) == "none"
        assert prompt_sha([]) == "none"
