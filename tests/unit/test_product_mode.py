"""Tests for product-mode enhancements.

Covers:
- ProductContext model validation and defaults
- ProductGateAnalyzer structured output parsing
- ProductGateState skip logic and transitions
- ProductGateReviewEvent and ProductDecisionEvent construction
- _is_trivial heuristic
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.domain.models.product_context import ProductContext, ProductAssumption
from weebot.domain.models.event import (
    ProductGateReviewEvent,
    ProductDecisionEvent,
    WaitForUserEvent,
    ThoughtEvent,
    ErrorEvent,
)
from weebot.application.services.product_gate_analyzer import ProductGateAnalyzer


# ========================================================================
# Fixtures
# ========================================================================

def _mock_llm(response_text: str) -> MagicMock:
    """Create a mock LLMPort that returns *response_text*."""
    llm = MagicMock()
    response = MagicMock()
    response.content = response_text
    llm.chat = AsyncMock(return_value=response)
    return llm


def _make_session_context(product_context_dict: dict | None = None):
    """Create a mock session context with optional product_context in extra."""
    ctx = MagicMock()
    ctx.extra = {}
    if product_context_dict:
        ctx.extra["product_context"] = product_context_dict
    ctx.get = lambda k, d=None: ctx.extra.get(k, d)
    ctx.model_copy = lambda update=None: MagicMock(
        extra={**ctx.extra, **(update or {}).get("extra", {})}
    )
    return ctx


def _make_session(ctx=None):
    session = MagicMock()
    session.context = ctx or _make_session_context()
    session.model_copy = lambda update=None: MagicMock(
        context=update.get("context", ctx) if update else ctx
    )
    return session


def _make_flow(plan=None, session=None):
    """Create a mock PlanActFlow compatible with state execution."""
    flow = MagicMock()
    flow._plan = plan
    flow._session = session or _make_session()
    flow._model = "test-model"
    flow._llm = _mock_llm("{}")  # default low-confidence
    flow._log = MagicMock()
    flow.set_state = MagicMock()
    return flow


# ========================================================================
# ProductContext model tests
# ========================================================================

class TestProductContext:
    def test_defaults(self):
        """ProductContext should have sensible defaults."""
        ctx = ProductContext()
        assert ctx.problem == ""
        assert ctx.why_now == ""
        assert ctx.scope == ""
        assert ctx.success_metric == ""
        assert ctx.reversibility == "two-way"
        assert ctx.assumptions == []
        assert ctx.overall_confidence == 0.5
        assert ctx.generated_at == ""
        assert ctx.model_used == ""

    def test_full_construction(self):
        """ProductContext should accept all fields."""
        ctx = ProductContext(
            problem="User needs to track daily tasks",
            why_now="Current solution is too complex",
            scope="A single-page todo app with add/complete/delete",
            success_metric="User can add, complete, and delete without page reload",
            reversibility="two-way",
            assumptions=[
                ProductAssumption(text="User has a modern browser", status="assumed"),
                ProductAssumption(text="LocalStorage is sufficient", status="assumed"),
            ],
            overall_confidence=0.85,
            generated_at="2025-07-16T12:00:00Z",
            model_used="gpt-4o",
        )
        assert ctx.problem == "User needs to track daily tasks"
        assert len(ctx.assumptions) == 2
        assert ctx.assumptions[0].status == "assumed"
        assert ctx.overall_confidence == 0.85

    def test_confidence_bounds(self):
        """overall_confidence should reject values outside 0.0-1.0."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ProductContext(overall_confidence=1.5)
        with pytest.raises(pydantic.ValidationError):
            ProductContext(overall_confidence=-0.5)

    def test_reversibility_default_two_way(self):
        """reversibility should default to 'two-way'."""
        ctx = ProductContext()
        assert ctx.reversibility == "two-way"

    def test_model_dump_roundtrip(self):
        """ProductContext should serialize and deserialize cleanly."""
        ctx = ProductContext(
            problem="Test problem",
            why_now="Test why now",
            scope="Test scope",
            success_metric="Test metric",
            reversibility="one-way",
            assumptions=[
                ProductAssumption(text="Test assumption", status="unknown"),
            ],
            overall_confidence=0.7,
        )
        data = ctx.model_dump(mode="json")
        restored = ProductContext.model_validate(data)
        assert restored.problem == ctx.problem
        assert restored.overall_confidence == ctx.overall_confidence
        assert len(restored.assumptions) == len(ctx.assumptions)
        assert restored.assumptions[0].text == "Test assumption"


# ========================================================================
# ProductGateAnalyzer tests
# ========================================================================

class TestProductGateAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_returns_product_context(self):
        """A well-formed prompt should produce a filled ProductContext."""
        llm = _mock_llm(
            '{"problem": "User needs X", "why_now": "Competitor launched", '
            '"scope": "Build MVP with core flow", '
            '"success_metric": "Users can complete flow in <30s", '
            '"reversibility": "two-way", '
            '"assumptions": [{"text": "Users have accounts", "status": "assumed"}], '
            '"overall_confidence": 0.8}'
        )
        analyzer = ProductGateAnalyzer(llm=llm)
        ctx = await analyzer.analyze("Build a login system", model_id="test-model")

        assert ctx.problem == "User needs X"
        assert ctx.why_now == "Competitor launched"
        assert ctx.scope == "Build MVP with core flow"
        assert ctx.success_metric == "Users can complete flow in <30s"
        assert ctx.reversibility == "two-way"
        assert len(ctx.assumptions) == 1
        assert ctx.assumptions[0].text == "Users have accounts"
        assert ctx.overall_confidence == 0.8
        assert ctx.model_used == "test-model"
        assert ctx.generated_at != ""

    @pytest.mark.asyncio
    async def test_analyze_unknown_fields(self):
        """Vague requests should produce UNKNOWN fields."""
        llm = _mock_llm(
            '{"problem": "UNKNOWN — too vague", "why_now": "N/A", '
            '"scope": "UNKNOWN", "success_metric": "UNKNOWN", '
            '"reversibility": "two-way", "assumptions": [], '
            '"overall_confidence": 0.2}'
        )
        analyzer = ProductGateAnalyzer(llm=llm)
        ctx = await analyzer.analyze("Do something cool")

        low = analyzer.get_low_confidence_fields(ctx)
        assert "problem" in low
        assert "scope" in low
        assert "overall_confidence" in low

    @pytest.mark.asyncio
    async def test_analyze_unparseable_json_fails_open(self):
        """Malformed JSON response should return a default ProductContext."""
        llm = _mock_llm("this is not json at all")
        analyzer = ProductGateAnalyzer(llm=llm)
        ctx = await analyzer.analyze("Build something")

        assert ctx.overall_confidence == 0.0

    @pytest.mark.asyncio
    async def test_analyze_timeout_fails_open(self):
        """LLM timeout should return a default ProductContext."""
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=TimeoutError("LLM timed out"))
        analyzer = ProductGateAnalyzer(llm=llm, timeout_seconds=0.1)
        ctx = await analyzer.analyze("Build something")

        assert ctx.overall_confidence == 0.0

    @pytest.mark.asyncio
    async def test_generate_clarification_questions(self):
        """Low-confidence fields should produce targeted questions."""
        ctx = ProductContext(
            problem="UNKNOWN",
            why_now="UNKNOWN",
            scope="Build a thing",
            success_metric="UNKNOWN",
            overall_confidence=0.3,
        )
        analyzer = ProductGateAnalyzer(llm=MagicMock())
        questions = analyzer.generate_clarification_questions(ctx)

        assert len(questions) <= 3
        assert len(questions) > 0
        assert any("problem" in q.lower() or "user" in q.lower() for q in questions)

    @pytest.mark.asyncio
    async def test_is_confident(self):
        """is_confident should compare against threshold."""
        ctx_low = ProductContext(overall_confidence=0.3)
        ctx_high = ProductContext(overall_confidence=0.8)
        analyzer = ProductGateAnalyzer(llm=MagicMock())

        assert not analyzer.is_confident(ctx_low)
        assert analyzer.is_confident(ctx_high)


# ========================================================================
# ProductGateState tests
# ========================================================================

class TestProductGateState:
    @pytest.mark.asyncio
    async def test_trivial_prompt_skips_gate(self):
        """Short single-verb prompts should skip the gate entirely."""
        from weebot.application.flows.states.product_gate import ProductGateState

        flow = _make_flow()
        state = ProductGateState()
        events = []
        async for event in state.execute(flow, "echo hello"):
            events.append(event)

        # Should transition directly to PlanningState with no output events
        assert len(events) == 0
        flow.set_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_high_confidence_proceeds_to_planning(self):
        """High-confidence product context should emit a ThoughtEvent and proceed."""
        from weebot.application.flows.states.product_gate import ProductGateState

        llm = _mock_llm(
            '{"problem": "User needs task tracking", '
            '"why_now": "No good free options exist", '
            '"scope": "Single-page todo with local storage", '
            '"success_metric": "Add, complete, delete tasks without reload", '
            '"reversibility": "two-way", '
            '"assumptions": [{"text": "Browser supports localStorage", "status": "assumed"}], '
            '"overall_confidence": 0.9}'
        )
        session = _make_session()
        flow = _make_flow(session=session)
        flow._llm = llm

        state = ProductGateState()
        events = []
        async for event in state.execute(flow, "Build me a todo app with task management features"):
            events.append(event)

        # Should yield a ThoughtEvent with the product context
        thought_events = [e for e in events if isinstance(e, ThoughtEvent)]
        assert len(thought_events) == 1
        assert "User needs task tracking" in thought_events[0].thought
        assert "90%" in thought_events[0].thought  # formatted as percentage

        # Product context should be stored in session extra
        flow.set_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_low_confidence_pauses_for_clarification(self):
        """Low-confidence product context should emit ProductGateReviewEvent + WaitForUserEvent."""
        from weebot.application.flows.states.product_gate import ProductGateState

        llm = _mock_llm(
            '{"problem": "UNKNOWN — too vague", "why_now": "N/A", '
            '"scope": "UNKNOWN", "success_metric": "UNKNOWN", '
            '"reversibility": "two-way", "assumptions": [], '
            '"overall_confidence": 0.2}'
        )
        flow = _make_flow()
        flow._llm = llm

        state = ProductGateState()
        events = []
        async for event in state.execute(flow, "Do something cool and innovative for our users"):
            events.append(event)

        # Should yield ProductGateReviewEvent followed by WaitForUserEvent
        review_events = [e for e in events if isinstance(e, ProductGateReviewEvent)]
        wait_events = [e for e in events if isinstance(e, WaitForUserEvent)]

        assert len(review_events) == 1
        assert len(wait_events) == 1
        assert "low_confidence_fields" in review_events[0].model_dump()
        assert "clarification_questions" in review_events[0].model_dump()

        # Should NOT call set_state — flow pauses on WaitForUserEvent
        flow.set_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_with_clarification(self):
        """Resume with user clarification should enrich the prompt."""
        from weebot.application.flows.states.product_gate import ProductGateState

        llm = _mock_llm(
            '{"problem": "User needs task tracking", '
            '"why_now": "Current tools are too complex", '
            '"scope": "Simple todo with add/complete/delete", '
            '"success_metric": "Tasks are persisted and completable", '
            '"reversibility": "two-way", '
            '"assumptions": [{"text": "Browser supports localStorage", "status": "assumed"}], '
            '"overall_confidence": 0.85}'
        )
        session = _make_session()
        flow = _make_flow(session=session)
        flow._llm = llm

        # Simulate resume after clarification
        state = ProductGateState(resume_with="I need a todo app for personal use, with local storage")
        events = []
        async for event in state.execute(flow, ""):
            events.append(event)

        # Should proceed with enriched context
        thought_events = [e for e in events if isinstance(e, ThoughtEvent)]
        assert len(thought_events) == 1

    @pytest.mark.asyncio
    async def test_short_continuation_response_skips_gate(self):
        """Short continuation responses (e.g. 'yes') are under 6 words and skip the gate."""
        from weebot.application.flows.states.product_gate import ProductGateState

        flow = _make_flow()

        # Simulate "yes" being treated as continuation
        state = ProductGateState()
        events = []
        async for event in state.execute(flow, "yes"):
            events.append(event)

        # Trivial prompt → skip gate
        assert len(events) == 0


# ========================================================================
# Event model tests
# ========================================================================

class TestProductGateReviewEvent:
    def test_minimal_construction(self):
        """ProductGateReviewEvent should work with minimal fields."""
        event = ProductGateReviewEvent(
            product_context={"problem": "test"},
            low_confidence_fields=["problem"],
            clarification_questions=["Who is the user?"],
        )
        assert event.type == "product_gate_review"
        assert event.product_context["problem"] == "test"
        assert len(event.low_confidence_fields) == 1
        assert len(event.clarification_questions) == 1

    def test_defaults(self):
        """ProductGateReviewEvent should have sensible defaults."""
        event = ProductGateReviewEvent()
        assert event.type == "product_gate_review"
        assert event.product_context == {}
        assert event.low_confidence_fields == []
        assert event.clarification_questions == []


class TestProductDecisionEvent:
    def test_minimal_construction(self):
        """ProductDecisionEvent should work with minimal fields."""
        event = ProductDecisionEvent(
            title="Session abc: task tracker",
            problem="User needs task tracking",
            choice="Built single-page todo app",
            session_id="test-session-123",
        )
        assert event.type == "product_decision"
        assert event.reversibility == "two-way"  # default
        assert event.title == "Session abc: task tracker"
        assert event.session_id == "test-session-123"

    def test_one_way_door(self):
        """One-way door decisions should be explicit."""
        event = ProductDecisionEvent(
            title="Schema migration",
            problem="Need to migrate User table",
            choice="Renamed email column",
            reversibility="one-way",
            session_id="test-456",
            revisit_trigger="Monitor error rate for 7 days",
        )
        assert event.reversibility == "one-way"
        assert event.revisit_trigger == "Monitor error rate for 7 days"

    def test_defaults(self):
        """ProductDecisionEvent should have sensible defaults."""
        event = ProductDecisionEvent()
        assert event.type == "product_decision"
        assert event.reversibility == "two-way"
        assert event.session_id == ""


# ========================================================================
# Feature flag tests
# ========================================================================

class TestFeatureFlags:
    def test_product_mode_off_by_default(self):
        """PRODUCT_MODE_ENABLED should default to False."""
        from weebot.config.feature_flags import PRODUCT_MODE_ENABLED
        assert PRODUCT_MODE_ENABLED is False

    def test_product_decision_log_off_by_default(self):
        """PRODUCT_DECISION_LOG_ENABLED should default to False."""
        from weebot.config.feature_flags import PRODUCT_DECISION_LOG_ENABLED
        assert PRODUCT_DECISION_LOG_ENABLED is False

    @patch.dict("os.environ", {"WEEBOT_PRODUCT_MODE": "true"})
    def test_product_mode_on_via_env(self):
        """WEEBOT_PRODUCT_MODE=true should enable the flag."""
        from importlib import reload
        import weebot.config.feature_flags as flags
        reload(flags)
        assert flags.PRODUCT_MODE_ENABLED is True
        # Reset for other tests
        reload(flags)

    @patch.dict("os.environ", {"WEEBOT_PRODUCT_DECISION_LOG": "1"})
    def test_product_decision_log_on_via_env(self):
        """WEEBOT_PRODUCT_DECISION_LOG=1 should enable the flag."""
        from importlib import reload
        import weebot.config.feature_flags as flags
        reload(flags)
        assert flags.PRODUCT_DECISION_LOG_ENABLED is True
        reload(flags)
