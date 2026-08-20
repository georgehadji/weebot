"""Unit tests for CodeReviewerService, including Ponytail static hints."""

from __future__ import annotations

from typing import Any

import pytest

from weebot.application.ports.llm_port import LLMPort
from weebot.application.services.code_reviewer_service import CodeReviewerService
from weebot.application.services.ponytail_static_review import static_ponytail_review
from weebot.domain.models.llm_response import LLMResponse
from weebot.domain.models.plan import Step


class _FakeLLMPort(LLMPort):
    """LLMPort that returns a fixed JSON review response."""

    def __init__(self, content: str) -> None:
        self._content = content

    async def chat(
        self,
        messages,
        tools=None,
        tool_choice="auto",
        response_format=None,
        model=None,
        temperature=None,
        max_tokens=None,
    ) -> LLMResponse:
        return LLMResponse(content=self._content, model="fake")


def _build_valid_review_json(issues: list[str] | None = None) -> str:
    issues = issues or []
    return (
        '{"verdict": "approved", "issues": ["'
        + '", "'.join(issues)
        + '"], "hint": "", "confidence": 0.9, "severity": "info", "over_engineered": false}'
    )


@pytest.fixture
def valid_llm_response() -> str:
    return _build_valid_review_json(["ok"])


class TestStaticPonytailReview:
    """Direct tests for the static Ponytail heuristics."""

    def test_empty_code_returns_no_findings(self):
        assert static_ponytail_review("") == []
        assert static_ponytail_review("   ") == []

    def test_single_implementation_abc_flagged(self):
        code = (
            "from abc import ABC\n\n"
            "class Greeter(ABC):\n    pass\n\n"
            "class DefaultGreeter(Greeter):\n    pass\n"
        )
        findings = static_ponytail_review(code)
        assert any("abstract base with a single implementation" in f for f in findings)

    def test_dict_loop_flagged(self):
        code = "items = {}\nfor k in keys:\n    items[k] = values[k]\n"
        findings = static_ponytail_review(code)
        assert any("dict(zip" in f for f in findings)

    def test_retrying_import_flagged(self):
        findings = static_ponytail_review("import retrying\n")
        assert any("retrying" in f for f in findings)


class TestCodeReviewerServicePonytail:
    """CodeReviewerService integration with Ponytail static hints."""

    @pytest.mark.asyncio
    async def test_off_mode_does_not_add_static_findings(self, monkeypatch, valid_llm_response):
        monkeypatch.setattr(
            "weebot.application.services.code_reviewer_service.get_ponytail_mode", lambda: "off"
        )
        step = Step(id="s1", description="write code", result="import retrying\n")
        service = CodeReviewerService(llm=_FakeLLMPort(valid_llm_response))

        result = await service.review(step, {})

        assert result.issues == ["ok"]

    @pytest.mark.asyncio
    async def test_full_mode_adds_static_findings_to_issues(self, monkeypatch, valid_llm_response):
        monkeypatch.setattr(
            "weebot.application.services.code_reviewer_service.get_ponytail_mode", lambda: "full"
        )
        step = Step(id="s1", description="write code", result="import retrying\n")
        service = CodeReviewerService(llm=_FakeLLMPort(valid_llm_response))

        result = await service.review(step, {})

        assert any("retrying" in issue for issue in result.issues)
        assert "ok" in result.issues

    @pytest.mark.asyncio
    async def test_full_mode_includes_static_findings_in_prompt(
        self, monkeypatch, valid_llm_response
    ):
        monkeypatch.setattr(
            "weebot.application.services.code_reviewer_service.get_ponytail_mode", lambda: "full"
        )

        captured_messages: list[dict[str, Any]] = []

        class _CapturingLLMPort(LLMPort):
            async def chat(self, messages, **kwargs) -> LLMResponse:
                captured_messages.extend(messages)
                return LLMResponse(content=valid_llm_response, model="fake")

        step = Step(id="s1", description="write code", result="import retrying\n")
        service = CodeReviewerService(llm=_CapturingLLMPort())
        await service.review(step, {})

        user_content = captured_messages[1]["content"]
        assert "Static Ponytail Hints" in user_content
        assert "retrying" in user_content
        system_content = captured_messages[0]["content"]
        assert "[Ponytail mode: full]" in system_content
