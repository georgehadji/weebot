"""Tests for SessionConstraintAccumulator (Phase 3 collaborator).

Extracted from plan_act_flow.py to keep that file under its allowlisted
line budget — see tasks/specs/side_constraint_integrity_plan.md Phase 3.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from weebot.application.flows.collaborators.session_constraint_accumulator import (
    SessionConstraintAccumulator,
)
from weebot.application.services.session_constraint_extractor import (
    ExtractionResult,
    SessionConstraintExtractor,
)
from weebot.domain.models.event import SessionConstraintRecorded, SessionConstraintRevoked
from weebot.domain.models.session_constraint import SessionConstraint, SessionConstraintRegistry


class TestHydrate:
    async def test_no_state_repo_returns_empty_registry(self):
        acc = SessionConstraintAccumulator(SessionConstraintExtractor(), state_repo=None)
        registry = await acc.hydrate("sess-1")
        assert registry.constraints == []

    async def test_hydrates_from_state_repo_rows(self):
        state_repo = AsyncMock()
        state_repo.list_active_session_constraints.return_value = [
            {"text": "never delete files", "evidence_span": "never delete files",
             "kind": "action", "direction": "tighten", "turn_index": 0},
        ]
        acc = SessionConstraintAccumulator(SessionConstraintExtractor(), state_repo=state_repo)
        registry = await acc.hydrate("sess-1")
        assert [c.text for c in registry.active()] == ["never delete files"]

    async def test_state_repo_failure_degrades_to_empty_registry(self):
        state_repo = AsyncMock()
        state_repo.list_active_session_constraints.side_effect = RuntimeError("db down")
        acc = SessionConstraintAccumulator(SessionConstraintExtractor(), state_repo=state_repo)
        registry = await acc.hydrate("sess-1")
        assert registry.constraints == []


class TestExtractAndApply:
    async def test_extracted_constraint_persisted_and_published(self):
        state_repo = AsyncMock()
        event_bus = AsyncMock()
        acc = SessionConstraintAccumulator(
            SessionConstraintExtractor(), state_repo=state_repo, event_bus=event_bus,
        )
        registry = await acc.extract_and_apply(
            "sess-1", "Never delete files without asking me first.",
            SessionConstraintRegistry(), turn_index=0,
        )
        assert registry.active()
        assert state_repo.save_session_constraint.await_count == 1
        published = event_bus.publish_domain_event.await_args.args[0]
        assert isinstance(published, SessionConstraintRecorded)

    async def test_no_op_when_no_constraint_in_text(self):
        state_repo = AsyncMock()
        acc = SessionConstraintAccumulator(SessionConstraintExtractor(), state_repo=state_repo)
        registry = await acc.extract_and_apply(
            "sess-1", "please summarize this pdf", SessionConstraintRegistry(), turn_index=0,
        )
        assert registry.active() == []
        assert state_repo.save_session_constraint.await_count == 0

    async def test_extraction_failure_returns_registry_unchanged(self):
        broken_extractor = AsyncMock()
        broken_extractor.extract.side_effect = RuntimeError("boom")
        acc = SessionConstraintAccumulator(broken_extractor)
        original = SessionConstraintRegistry()
        result = await acc.extract_and_apply(
            "sess-1", "never delete files", original, turn_index=0,
        )
        assert result is original  # unchanged, no raise

    async def test_persistence_failure_does_not_block_in_memory_update(self):
        state_repo = AsyncMock()
        state_repo.save_session_constraint.side_effect = RuntimeError("write failed")
        acc = SessionConstraintAccumulator(SessionConstraintExtractor(), state_repo=state_repo)
        registry = await acc.extract_and_apply(
            "sess-1", "Never delete files without asking me first.",
            SessionConstraintRegistry(), turn_index=0,
        )
        # DB write failed but the returned registry still reflects extraction
        # (so same-turn rendering in Phase 4 isn't starved by a DB blip).
        assert registry.active()

    async def test_revocation_persisted_and_published(self):
        state_repo = AsyncMock()
        event_bus = AsyncMock()

        class _RevokingExtractor:
            async def extract(self, *a, **kw):
                return ExtractionResult(added=[], revoked_texts=["never delete files"])

        acc = SessionConstraintAccumulator(
            _RevokingExtractor(), state_repo=state_repo, event_bus=event_bus,
        )
        seeded = SessionConstraintRegistry().add(
            SessionConstraint(text="never delete files", evidence_span="never delete files")
        )
        registry = await acc.extract_and_apply(
            "sess-1", "actually go ahead and delete them", seeded, turn_index=1,
        )
        assert registry.active() == []
        assert state_repo.revoke_session_constraint.await_count == 1
        published = event_bus.publish_domain_event.await_args.args[0]
        assert isinstance(published, SessionConstraintRevoked)

    async def test_no_event_bus_does_not_raise(self):
        acc = SessionConstraintAccumulator(SessionConstraintExtractor(), state_repo=None, event_bus=None)
        registry = await acc.extract_and_apply(
            "sess-1", "Never delete files without asking me first.",
            SessionConstraintRegistry(), turn_index=0,
        )
        assert registry.active()
