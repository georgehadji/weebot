"""Unit tests for StepProgressEvaluator (Improvement #6)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.ports.step_evaluator_port import StepEvaluation
from weebot.application.services.step_evaluator import NoOpStepEvaluator, LLMStepEvaluator
from weebot.domain.models.plan import Plan, Step


class TestNoOpStepEvaluator:
    """NoOpStepEvaluator always passes — backward-compatible default."""

    @pytest.mark.asyncio
    async def test_always_passes_with_positive_score(self):
        evaluator = NoOpStepEvaluator()
        step = Step(id="s1", description="test step")
        plan = Plan(title="test plan", steps=[step])
        result = await evaluator.evaluate(step, "some output", plan, [])
        assert result.passed is True
        assert result.score == 1.0
        assert result.regression_detected is False

    @pytest.mark.asyncio
    async def test_works_with_empty_output(self):
        evaluator = NoOpStepEvaluator()
        step = Step(id="s1", description="test")
        plan = Plan(title="p", steps=[step])
        result = await evaluator.evaluate(step, "", plan, [])
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_works_with_previous_outputs(self):
        evaluator = NoOpStepEvaluator()
        step = Step(id="s2", description="step 2")
        plan = Plan(title="p", steps=[Step(id="s1", description="step 1"), step])
        result = await evaluator.evaluate(step, "output 2", plan, ["output 1"])
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_step_evaluation_fields_are_frozen(self):
        result = StepEvaluation(
            step_id="s1", score=0.8, passed=True, regression_detected=False, reasoning="good"
        )
        assert result.score == 0.8
        with pytest.raises(Exception):
            result.score = 0.5  # frozen dataclass


class TestLLMStepEvaluator:
    """LLMStepEvaluator scores output via LLM, fails open on errors."""

    def _make_mock_llm(self, json_response: dict):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = __import__("json").dumps(json_response)
        mock_llm.chat = AsyncMock(return_value=mock_resp)
        return mock_llm

    @pytest.mark.asyncio
    async def test_high_score_passes(self):
        llm = self._make_mock_llm(
            {
                "score": 0.9,
                "regression_detected": False,
                "reasoning": "excellent work",
                "recommendations": [],
            }
        )
        evaluator = LLMStepEvaluator(llm=llm, threshold=0.4)
        step = Step(id="s1", description="implement feature")
        plan = Plan(title="build app", steps=[step])
        result = await evaluator.evaluate(step, "implemented correctly", plan, [])
        assert result.passed is True
        assert result.score == 0.9

    @pytest.mark.asyncio
    async def test_low_score_fails(self):
        llm = self._make_mock_llm(
            {
                "score": 0.2,
                "regression_detected": False,
                "reasoning": "incomplete",
                "recommendations": ["retry"],
            }
        )
        evaluator = LLMStepEvaluator(llm=llm, threshold=0.4)
        step = Step(id="s1", description="implement feature")
        plan = Plan(title="build app", steps=[step])
        result = await evaluator.evaluate(step, "partial output", plan, [])
        assert result.passed is False
        assert result.score == 0.2

    @pytest.mark.asyncio
    async def test_regression_fails_even_with_high_score(self):
        llm = self._make_mock_llm(
            {
                "score": 0.8,
                "regression_detected": True,
                "reasoning": "reverted previous work",
                "recommendations": ["check git diff"],
            }
        )
        evaluator = LLMStepEvaluator(llm=llm, threshold=0.4)
        step = Step(id="s1", description="refactor")
        plan = Plan(title="cleanup", steps=[step])
        result = await evaluator.evaluate(step, "deleted feature", plan, ["had feature"])
        assert result.passed is False
        assert result.regression_detected is True

    @pytest.mark.asyncio
    async def test_fail_open_on_llm_error(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        evaluator = LLMStepEvaluator(llm=mock_llm, threshold=0.4)
        step = Step(id="s1", description="test")
        plan = Plan(title="test", steps=[step])
        result = await evaluator.evaluate(step, "output", plan, [])
        assert result.passed is True  # fail-open
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_passes_previous_outputs_to_prompt(self):
        captured_messages = []
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = (
            '{"score": 0.7, "regression_detected": false, "reasoning": "ok", "recommendations": []}'
        )

        async def capture_chat(messages, **kwargs):
            captured_messages.append(messages)
            return mock_resp

        mock_llm.chat = capture_chat
        evaluator = LLMStepEvaluator(llm=mock_llm, threshold=0.4)
        step = Step(id="s2", description="build UI")
        plan = Plan(title="app", steps=[Step(id="s1", description="setup"), step])
        await evaluator.evaluate(step, "built UI", plan, ["setup done"])

        prompt_text = captured_messages[0][0]["content"]
        assert "setup done" in prompt_text


class TestInstrumentFailureIsVisible:
    """W2: if this gate's own machinery fails, does it report clean?

    `json.loads(resp.content or "{}")` parsed an empty completion into `{}`, and
    `.get("score", 1.0)` then manufactured a perfect score. No exception was
    raised, so the fail-open warning never fired and `reasoning` stayed empty --
    a silently-broken evaluator was indistinguishable from one passing every
    step on merit. The consumer at flows/states/executing.py:623 routes
    `not passed` to UpdatingState, so a broken evaluator skipped the plan
    revision it exists to trigger.

    Failing open on `passed` is documented and intentional; being
    indistinguishable was not.
    """

    @staticmethod
    def _evaluator(content):
        from weebot.domain.models.llm_response import LLMResponse

        llm = MagicMock()
        llm.chat = AsyncMock(return_value=LLMResponse(content=content))
        return LLMStepEvaluator(llm=llm)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("content", ["", None, "   ", "I'm sorry, I can't help."])
    async def test_unusable_completion_is_reported_as_a_failure(self, content):
        step = Step(id="s1", description="do the thing")
        plan = Plan(title="goal", steps=[step])

        result = await self._evaluator(content).evaluate(step, "output", plan, [])

        assert result.reasoning.startswith("evaluation failed:"), (
            f"a {content!r} completion must be distinguishable from a real pass"
        )

    @pytest.mark.asyncio
    async def test_json_without_a_score_field_is_a_failure(self):
        """`.get("score", 1.0)` invented a perfect score for a scoreless reply."""
        step = Step(id="s1", description="do the thing")
        plan = Plan(title="goal", steps=[step])

        result = await self._evaluator('{"reasoning": "looks fine"}').evaluate(
            step, "output", plan, []
        )

        assert result.reasoning.startswith("evaluation failed:")

    @pytest.mark.asyncio
    async def test_fail_open_is_preserved(self):
        """Execution must still not block on a broken evaluator."""
        step = Step(id="s1", description="do the thing")
        plan = Plan(title="goal", steps=[step])

        assert (await self._evaluator("").evaluate(step, "o", plan, [])).passed is True

    @pytest.mark.asyncio
    async def test_a_real_verdict_is_untouched(self):
        """No-regression: a well-formed low score still fails the step."""
        step = Step(id="s1", description="do the thing")
        plan = Plan(title="goal", steps=[step])

        result = await self._evaluator(
            '{"score": 0.1, "regression_detected": false, "reasoning": "no progress"}'
        ).evaluate(step, "output", plan, [])

        assert result.passed is False
        assert result.score == 0.1
        assert result.reasoning == "no progress"
