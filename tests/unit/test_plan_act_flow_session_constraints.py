"""Tests for PlanActFlow's session-constraint accumulation (Phase 3).

Exercises _extract_session_constraints / _hydrate_constraint_registry
directly rather than driving the full run() generator -- these are the
flow-entry seam per tasks/specs/side_constraint_integrity_plan.md Phase 3.
"""

from __future__ import annotations

from unittest.mock import AsyncMock


from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.services.session_constraint_extractor import SessionConstraintExtractor
from weebot.domain.models.event import SessionConstraintRecorded, SessionConstraintRevoked
from weebot.domain.models.session import Session


def _flow(*, sc_extractor=None, state_repo=None, event_bus=None) -> PlanActFlow:
    return PlanActFlow(
        llm=AsyncMock(),
        tools=ToolCollection(),
        session=Session(id="sess-1"),
        state_repo=state_repo,
        event_bus=event_bus,
        session_constraint_extractor=sc_extractor,
    )


class TestConstructorWiring:
    def test_extractor_reaches_flow_via_legacy_kwarg(self):
        extractor = SessionConstraintExtractor()
        flow = _flow(sc_extractor=extractor)
        assert flow._sc_extractor is extractor

    def test_none_by_default_backward_compatible(self):
        flow = _flow()
        assert flow._sc_extractor is None


class TestExtractionWiring:
    """Hydration itself is covered by test_session_constraint_accumulator.py —
    these exercise PlanActFlow's delegation to SessionConstraintAccumulator."""

    async def test_extracted_constraint_persisted_and_published(self):
        state_repo = AsyncMock()
        state_repo.list_active_session_constraints.return_value = []
        event_bus = AsyncMock()
        flow = _flow(
            sc_extractor=SessionConstraintExtractor(), state_repo=state_repo, event_bus=event_bus
        )

        await flow._extract_session_constraints("Never delete files without asking me first.")

        assert state_repo.save_session_constraint.await_count == 1
        published = event_bus.publish_domain_event.await_args.args[0]
        assert isinstance(published, SessionConstraintRecorded)
        assert (
            flow._session_constraints.active()
        ), "in-memory registry should hold the new constraint"

    async def test_no_op_when_no_constraint_in_text(self):
        state_repo = AsyncMock()
        state_repo.list_active_session_constraints.return_value = []
        flow = _flow(sc_extractor=SessionConstraintExtractor(), state_repo=state_repo)

        await flow._extract_session_constraints("please summarize this pdf")

        assert state_repo.save_session_constraint.await_count == 0

    async def test_extraction_failure_does_not_raise(self):
        broken_extractor = AsyncMock()
        broken_extractor.extract.side_effect = RuntimeError("boom")
        flow = _flow(sc_extractor=broken_extractor)
        # Must not raise -- extraction failure is fail-open (plan D9).
        await flow._extract_session_constraints("never delete files")

    async def test_persistence_failure_does_not_block_in_memory_update(self):
        state_repo = AsyncMock()
        state_repo.list_active_session_constraints.return_value = []
        state_repo.save_session_constraint.side_effect = RuntimeError("write failed")
        flow = _flow(sc_extractor=SessionConstraintExtractor(), state_repo=state_repo)

        await flow._extract_session_constraints("Never delete files without asking me first.")

        # DB write failed, but the in-memory registry (used by Phase 4
        # rendering this same turn) still reflects the extraction.
        assert flow._session_constraints.active()

    async def test_revocation_persisted_and_published(self):
        state_repo = AsyncMock()
        state_repo.list_active_session_constraints.return_value = [
            {
                "text": "never delete files",
                "evidence_span": "never delete files",
                "kind": "action",
                "direction": "tighten",
                "turn_index": 0,
            }
        ]
        event_bus = AsyncMock()

        class _RevokingExtractor:
            async def extract(self, *a, **kw):
                from weebot.application.services.session_constraint_extractor import (
                    ExtractionResult,
                )

                return ExtractionResult(added=[], revoked_texts=["never delete files"])

        flow = _flow(sc_extractor=_RevokingExtractor(), state_repo=state_repo, event_bus=event_bus)

        await flow._extract_session_constraints("actually go ahead and delete them")

        assert state_repo.revoke_session_constraint.await_count == 1
        published = event_bus.publish_domain_event.await_args.args[0]
        assert isinstance(published, SessionConstraintRevoked)
        assert flow._session_constraints.active() == []

    def test_flow_without_extractor_stays_none(self):
        """Backward compat: flows built without session_constraint_extractor
        (every existing call site, pre-Phase-3) must be unaffected."""
        flow = _flow()  # sc_extractor is None
        assert flow._sc_extractor is None
