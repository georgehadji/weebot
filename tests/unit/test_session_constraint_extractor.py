"""Tests for SessionConstraintExtractor.

Phase 2 of tasks/specs/side_constraint_integrity_plan.md. Coverage is
measured against a subset of the paper's 15 benchmark side constraints
(the full 15/15 harness is Phase 6) plus the tiering/fallback contract
mirrored from CorrectionTracker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


from weebot.application.services.session_constraint_extractor import SessionConstraintExtractor
from weebot.domain.models.session_constraint import (
    ConstraintDirection,
    ConstraintKind,
    SessionConstraintRegistry,
)


@dataclass
class _FakeResponse:
    content: str


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return _FakeResponse(self._content)


class _RaisingLLM:
    async def chat(self, **kwargs):
        raise RuntimeError("boom")


EMPTY_REGISTRY = SessionConstraintRegistry()


class TestTriggerGate:
    async def test_plain_task_text_extracts_nothing(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "please summarize this pdf for me", registry=EMPTY_REGISTRY
        )
        assert result.added == []

    async def test_empty_text_extracts_nothing(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract("", registry=EMPTY_REGISTRY)
        assert result.added == []


class TestHeuristicTierCoverage:
    """Representative sentences across the paper's five SC categories."""

    async def test_action_negative(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "Don't send any messages or emails on my behalf, draft them and let me send them myself.",
            registry=EMPTY_REGISTRY,
        )
        assert any(c.kind == ConstraintKind.ACTION for c in result.added)
        assert all(c.direction == ConstraintDirection.TIGHTEN for c in result.added)

    async def test_action_positively_framed(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "Before you run a command, show me what you're about to do and wait for my go-ahead.",
            registry=EMPTY_REGISTRY,
        )
        assert any(c.kind == ConstraintKind.ACTION for c in result.added)

    async def test_output_reply_format(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "Reply in bullet points only, no paragraphs.", registry=EMPTY_REGISTRY
        )
        assert any(c.kind == ConstraintKind.OUTPUT for c in result.added)

    async def test_output_end_every_reply(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "End every reply with this exact sentence: 'Let me know if you need anything else.'",
            registry=EMPTY_REGISTRY,
        )
        assert any(c.kind == ConstraintKind.OUTPUT for c in result.added)

    async def test_preference_over(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "When you recommend papers, prefer arXiv ones over peer-reviewed venues.",
            registry=EMPTY_REGISTRY,
        )
        assert any(c.kind == ConstraintKind.PREFERENCE for c in result.added)

    async def test_preference_use_not(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract("Use metric units, not imperial.", registry=EMPTY_REGISTRY)
        assert any(c.kind == ConstraintKind.PREFERENCE for c in result.added)

    async def test_process_always_before(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "Always do a web search before answering, even for things you think you know.",
            registry=EMPTY_REGISTRY,
        )
        assert any(c.kind == ConstraintKind.PROCESS for c in result.added)

    async def test_information_never_include(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "Never include my name in your replies or in any tool call.", registry=EMPTY_REGISTRY
        )
        assert any(c.kind == ConstraintKind.INFORMATION for c in result.added)


class TestLoosenDirection:
    async def test_permission_widening_constraint_marked_loosen(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "Don't ask me to confirm before running commands, just do them.",
            registry=EMPTY_REGISTRY,
        )
        assert result.added, "expected at least one extracted constraint"
        assert all(c.direction == ConstraintDirection.LOOSEN for c in result.added)

    async def test_ordinary_prohibition_stays_tighten(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "Never delete files without asking me first.", registry=EMPTY_REGISTRY
        )
        assert result.added
        assert all(c.direction == ConstraintDirection.TIGHTEN for c in result.added)


class TestDedup:
    async def test_duplicate_matches_within_one_turn_collapse(self):
        extractor = SessionConstraintExtractor()
        result = await extractor.extract(
            "Never delete files. Never delete files.", registry=EMPTY_REGISTRY
        )
        texts = [c.text.lower() for c in result.added]
        assert len(texts) == len(set(texts))


class TestLLMTier:
    async def test_llm_used_when_configured(self):
        payload = json.dumps(
            {
                "add": [
                    {
                        "text": "always use metric units",
                        "evidence_span": "use metric, not imperial",
                        "kind": "preference",
                        "direction": "tighten",
                    }
                ],
                "revoke": [],
            }
        )
        llm = _FakeLLM(payload)
        extractor = SessionConstraintExtractor(llm=llm)
        result = await extractor.extract(
            "When you give measurements, use metric, not imperial.", registry=EMPTY_REGISTRY
        )
        assert llm.calls == 1
        assert len(result.added) == 1
        assert result.added[0].kind == ConstraintKind.PREFERENCE

    async def test_llm_revocation_parsed(self):
        payload = json.dumps({"add": [], "revoke": ["never delete files"]})
        llm = _FakeLLM(payload)
        extractor = SessionConstraintExtractor(llm=llm)
        result = await extractor.extract(
            "Actually, go ahead and delete them now.", registry=EMPTY_REGISTRY
        )
        assert result.revoked_texts == ["never delete files"]

    async def test_llm_invalid_kind_is_dropped(self):
        payload = json.dumps(
            {
                "add": [
                    {"text": "x", "evidence_span": "x", "kind": "bogus", "direction": "tighten"}
                ],
                "revoke": [],
            }
        )
        extractor = SessionConstraintExtractor(llm=_FakeLLM(payload))
        result = await extractor.extract("never do x", registry=EMPTY_REGISTRY)
        assert result.added == []

    async def test_llm_malformed_json_degrades_to_empty(self):
        extractor = SessionConstraintExtractor(llm=_FakeLLM("not json at all"))
        result = await extractor.extract("never do x", registry=EMPTY_REGISTRY)
        assert result.added == []
        assert result.revoked_texts == []

    async def test_llm_failure_falls_back_to_heuristic(self):
        extractor = SessionConstraintExtractor(llm=_RaisingLLM())
        result = await extractor.extract(
            "Never delete files without asking me first.", registry=EMPTY_REGISTRY
        )
        # Heuristic tier still runs and finds the negative-action pattern.
        assert result.added
        assert result.added[0].kind == ConstraintKind.ACTION
