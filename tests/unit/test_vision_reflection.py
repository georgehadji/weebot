"""Tests for Phase 2 vision reflection: PageObservation, NextActionPlan, executor integration.

TDD — written before implementation.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.models.structured_output import NextActionPlan, PageObservation, VisionReflection

_B64 = "aGVsbG8="  # base64("hello") — tiny valid-ish payload


# ── Model validation ─────────────────────────────────────────────────────────

class TestPageObservation:
    def test_minimal_valid(self):
        obs = PageObservation(summary="Calculator open", key_elements=["display", "buttons"])
        assert obs.is_task_complete is False
        assert 0.0 <= obs.confidence <= 1.0

    def test_complete_flag(self):
        obs = PageObservation(
            summary="Task done", key_elements=[], is_task_complete=True, confidence=0.95
        )
        assert obs.is_task_complete is True

    def test_confidence_clamped(self):
        with pytest.raises(Exception):
            PageObservation(summary="x", key_elements=[], confidence=1.5)

    def test_serialises_to_json(self):
        obs = PageObservation(summary="s", key_elements=["a"])
        d = obs.model_dump()
        assert d["summary"] == "s"
        assert d["key_elements"] == ["a"]


class TestNextActionPlan:
    def test_minimal_valid(self):
        plan = NextActionPlan(
            action_type="click",
            reasoning="button is visible",
            expected_outcome="dialog opens",
        )
        assert plan.selector is None
        assert plan.coordinates is None

    def test_all_action_types_accepted(self):
        for at in ("click", "type", "scroll", "navigate", "wait", "none"):
            p = NextActionPlan(action_type=at, reasoning="r", expected_outcome="o")
            assert p.action_type == at

    def test_invalid_action_type_raises(self):
        with pytest.raises(Exception):
            NextActionPlan(action_type="explode", reasoning="r", expected_outcome="o")

    def test_coordinates_dict(self):
        plan = NextActionPlan(
            action_type="click",
            coordinates={"x": 100, "y": 200},
            reasoning="unlabeled icon at position",
            expected_outcome="menu opens",
        )
        assert plan.coordinates == {"x": 100, "y": 200}


class TestVisionReflection:
    def test_round_trip(self):
        r = VisionReflection(
            observation=PageObservation(summary="s", key_elements=["e1"]),
            plan=NextActionPlan(action_type="none", reasoning="done", expected_outcome="nothing"),
        )
        data = r.model_dump()
        r2 = VisionReflection.model_validate(data)
        assert r2.observation.summary == "s"
        assert r2.plan.action_type == "none"

    def test_from_json_string(self):
        raw = json.dumps({
            "observation": {
                "summary": "Browser open",
                "key_elements": ["address bar", "tab"],
                "is_task_complete": False,
                "confidence": 0.8,
            },
            "plan": {
                "action_type": "click",
                "selector": "#submit",
                "reasoning": "submit form",
                "expected_outcome": "page navigates",
                "confidence": 0.7,
            },
        })
        r = VisionReflection.model_validate(json.loads(raw))
        assert r.observation.confidence == 0.8
        assert r.plan.selector == "#submit"


# ── ExecutorAgent integration ─────────────────────────────────────────────────

def _make_executor(model: str = "claude-opus-4-8"):
    from weebot.application.agents.executor._base import ExecutorAgent
    from weebot.application.models.tool_collection import ToolCollection
    return ExecutorAgent(llm=MagicMock(), tools=ToolCollection(), model=model)


class TestReflectionEnabled:
    def test_reflection_requires_both_flags(self, monkeypatch):
        import weebot.config.feature_flags as ff
        monkeypatch.setattr(ff, "VISION_IN_LOOP_ENABLED", False, raising=False)
        monkeypatch.setattr(ff, "VISION_REFLECTION_ENABLED", True, raising=False)
        ex = _make_executor()
        assert ex._reflection_enabled() is False

    def test_reflection_requires_vision_flag(self, monkeypatch):
        import weebot.config.feature_flags as ff
        monkeypatch.setattr(ff, "VISION_IN_LOOP_ENABLED", True, raising=False)
        monkeypatch.setattr(ff, "VISION_REFLECTION_ENABLED", False, raising=False)
        ex = _make_executor()
        assert ex._reflection_enabled() is False

    def test_reflection_enabled_both_on(self, monkeypatch):
        import weebot.config.feature_flags as ff
        monkeypatch.setattr(ff, "VISION_IN_LOOP_ENABLED", True, raising=False)
        monkeypatch.setattr(ff, "VISION_REFLECTION_ENABLED", True, raising=False)
        ex = _make_executor("claude-opus-4-8")
        assert ex._reflection_enabled() is True

    def test_reflection_off_for_non_vision_model(self, monkeypatch):
        import weebot.config.feature_flags as ff
        monkeypatch.setattr(ff, "VISION_IN_LOOP_ENABLED", True, raising=False)
        monkeypatch.setattr(ff, "VISION_REFLECTION_ENABLED", True, raising=False)
        ex = _make_executor("deepseek-chat")
        assert ex._reflection_enabled() is False


class TestReflectOnScreenshot:
    @pytest.mark.asyncio
    async def test_returns_reflection_on_valid_llm_response(self, monkeypatch):
        """_reflect_on_screenshot() returns VisionReflection when LLM gives valid JSON."""
        import weebot.config.feature_flags as ff
        monkeypatch.setattr(ff, "VISION_IN_LOOP_ENABLED", True, raising=False)
        monkeypatch.setattr(ff, "VISION_REFLECTION_ENABLED", True, raising=False)

        from weebot.application.ports.llm_port import LLMResponse
        good_json = json.dumps({
            "observation": {
                "summary": "Desktop visible",
                "key_elements": ["taskbar", "icons"],
                "is_task_complete": False,
                "confidence": 0.9,
            },
            "plan": {
                "action_type": "click",
                "selector": None,
                "coordinates": {"x": 50, "y": 50},
                "reasoning": "icon visible at top-left",
                "expected_outcome": "app opens",
                "confidence": 0.8,
            },
        })
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(
            content=good_json, tool_calls=None, model="claude-opus-4-8"
        ))

        from weebot.application.agents.executor._base import ExecutorAgent
        from weebot.application.models.tool_collection import ToolCollection
        ex = ExecutorAgent(llm=mock_llm, tools=ToolCollection(), model="claude-opus-4-8")

        result = await ex._reflect_on_screenshot("computer_use", _B64)
        assert result is not None
        assert result.observation.summary == "Desktop visible"
        assert result.plan.action_type == "click"
        assert result.plan.expected_outcome == "app opens"

    @pytest.mark.asyncio
    async def test_returns_none_on_malformed_json(self, monkeypatch):
        """Reflection errors must never raise — graceful degradation."""
        import weebot.config.feature_flags as ff
        monkeypatch.setattr(ff, "VISION_IN_LOOP_ENABLED", True, raising=False)
        monkeypatch.setattr(ff, "VISION_REFLECTION_ENABLED", True, raising=False)

        from weebot.application.ports.llm_port import LLMResponse
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(
            content="not json at all", tool_calls=None, model="claude-opus-4-8"
        ))

        from weebot.application.agents.executor._base import ExecutorAgent
        from weebot.application.models.tool_collection import ToolCollection
        ex = ExecutorAgent(llm=mock_llm, tools=ToolCollection(), model="claude-opus-4-8")

        result = await ex._reflect_on_screenshot("screen_tool", _B64)
        assert result is None  # graceful degradation

    @pytest.mark.asyncio
    async def test_returns_none_when_reflection_disabled(self, monkeypatch):
        import weebot.config.feature_flags as ff
        monkeypatch.setattr(ff, "VISION_REFLECTION_ENABLED", False, raising=False)

        ex = _make_executor()
        result = await ex._reflect_on_screenshot("computer_use", _B64)
        assert result is None


class TestInjectReflection:
    def test_reflection_appended_as_system_message(self):
        """_inject_reflection() adds a system message with the observation summary."""
        ex = _make_executor()
        reflection = VisionReflection(
            observation=PageObservation(
                summary="File dialog open",
                key_elements=["filename field", "Open button"],
                is_task_complete=False,
                confidence=0.85,
            ),
            plan=NextActionPlan(
                action_type="type",
                selector=None,
                value="report.pdf",
                reasoning="filename field is empty",
                expected_outcome="filename field shows report.pdf",
                confidence=0.9,
            ),
        )
        ex._inject_reflection(reflection)

        msgs = list(ex._conversation_buffer)
        assert msgs, "No messages in buffer after reflection inject"
        last = msgs[-1]
        assert last["role"] == "system"
        assert "File dialog open" in last["content"]
        assert "report.pdf" in last["content"]

    def test_complete_task_flagged_in_system_message(self):
        """is_task_complete=True must surface prominently in the injected message."""
        ex = _make_executor()
        reflection = VisionReflection(
            observation=PageObservation(
                summary="Success dialog visible",
                key_elements=["OK button"],
                is_task_complete=True,
                confidence=0.95,
            ),
            plan=NextActionPlan(
                action_type="none",
                reasoning="task is done",
                expected_outcome="no more actions needed",
            ),
        )
        ex._inject_reflection(reflection)

        content = list(ex._conversation_buffer)[-1]["content"]
        assert "complete" in content.lower() or "COMPLETE" in content

    def test_expected_outcome_stored_for_self_correction(self):
        """Expected outcome from NextActionPlan is saved for the next screenshot comparison."""
        ex = _make_executor()
        reflection = VisionReflection(
            observation=PageObservation(summary="s", key_elements=[]),
            plan=NextActionPlan(
                action_type="click",
                reasoning="r",
                expected_outcome="dialog should appear",
            ),
        )
        ex._inject_reflection(reflection)
        assert ex._last_expected_outcome == "dialog should appear"
