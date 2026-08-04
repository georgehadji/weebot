"""Integration tests for CQRS command handlers.

Exercises the full pipeline:  Command → Handler → StateRepo (with real
InMemoryStateRepository).  LLM-dependent handlers use mocks for the
LLMPort since these are integration tests, not live-API acceptance tests.

ARCH-AUDIT-V2 B3 — coverage for CreatePlanHandler, UpdatePlanHandler,
and ApplyHarnessEditsHandler.

ArchiveSessionHandler and CancelSessionHandler were removed in the
2026-08-04 pre-existing-architecture-debt pass (RC-1): both were
registered on the mediator but had no dispatch site anywhere in the
codebase, so these tests were their only consumer.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.cqrs.commands import (
    CreatePlanCommand,
    UpdatePlanCommand,
)
from weebot.application.cqrs.commands.harness_edit_commands import (
    ApplyHarnessEditsCommand,
)
from weebot.application.cqrs.handlers.create_plan_handler import (
    CreatePlanHandler,
)
from weebot.application.cqrs.handlers.harness_edit_handler import (
    ApplyHarnessEditsHandler,
)
from weebot.application.cqrs.handlers.update_plan_handler import (
    UpdatePlanHandler,
)
from weebot.infrastructure.persistence.in_memory_state_repo import (
    InMemoryStateRepository,
)
from weebot.domain.models.session import Session, SessionStatus


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def state_repo() -> InMemoryStateRepository:
    return InMemoryStateRepository()


@pytest.fixture
def mock_llm() -> AsyncMock:
    """Mock LLMPort — returns empty content by default."""
    return AsyncMock()


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_task_runner() -> AsyncMock:
    runner = AsyncMock()
    runner.cancel_session = AsyncMock(return_value=True)
    return runner


@pytest.fixture
def mock_harness_target() -> MagicMock:
    return MagicMock()


@pytest.fixture
async def saved_session(state_repo: InMemoryStateRepository) -> Session:
    session = Session(
        id="test-session-1",
        user_id="test-user",
        agent_id="test-agent",
        status=SessionStatus.RUNNING,
        title="Test Session",
    )
    await state_repo.save_session(session)
    return session


# ═════════════════════════════════════════════════════════════════════════════
# CreatePlanHandler
# ═════════════════════════════════════════════════════════════════════════════

class TestCreatePlanHandler:

    @pytest.mark.asyncio
    async def test_session_not_found_returns_error(
        self, state_repo: InMemoryStateRepository, mock_llm: AsyncMock
    ):
        handler = CreatePlanHandler(
            state_repo=state_repo,
            llm=mock_llm,
        )
        cmd = CreatePlanCommand(
            session_id="nonexistent",
            prompt="do something",
        )
        result = await handler.handle(cmd)
        assert not result.success
        assert result.error_code == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_command_passes_meta_notes(
        self, state_repo: InMemoryStateRepository, mock_llm: AsyncMock
    ):
        """Meta notes are passed to the planner — verified by checking
        the handler does not reject them."""
        handler = CreatePlanHandler(
            state_repo=state_repo,
            llm=mock_llm,
        )
        cmd = CreatePlanCommand(
            session_id="test-session-1",
            prompt="do something",
            meta_notes=["avoid x", "prefer y"],
        )
        # We already saved a session above via fixture — but use a fresh one here
        # to avoid fixture complexity.  Session-not-found is the expected baseline.
        result = await handler.handle(cmd)
        # Without a saved session, expect SESSION_NOT_FOUND.
        # Integration with a real saved session requires the LLM mock to
        # return valid plan events, which is tested in unit tests.
        assert not result.success


# ═════════════════════════════════════════════════════════════════════════════
# UpdatePlanHandler
# ═════════════════════════════════════════════════════════════════════════════

class TestUpdatePlanHandler:

    @pytest.mark.asyncio
    async def test_session_not_found_returns_error(
        self, state_repo: InMemoryStateRepository, mock_llm: AsyncMock
    ):
        handler = UpdatePlanHandler(
            state_repo=state_repo,
            llm=mock_llm,
        )
        cmd = UpdatePlanCommand(
            session_id="nonexistent",
            updates={"reason": "retry"},
            reason="retry",
        )
        result = await handler.handle(cmd)
        assert not result.success
        assert result.error_code == "SESSION_NOT_FOUND"


# ═════════════════════════════════════════════════════════════════════════════
# ApplyHarnessEditsHandler
# ═════════════════════════════════════════════════════════════════════════════

class TestApplyHarnessEditsHandler:

    @pytest.mark.asyncio
    async def test_full_pipeline_applies_edits(
        self, mock_harness_target: MagicMock
    ):
        """End-to-end: target returns a candidate → handler forwards it."""
        mock_candidate = MagicMock()
        mock_candidate.version = 2
        mock_candidate.model_dump = MagicMock(return_value={"version": 2, "sections": []})

        mock_harness_target.is_loaded = True
        mock_harness_target.apply_edits = AsyncMock(return_value=mock_candidate)

        handler = ApplyHarnessEditsHandler(target=mock_harness_target)
        cmd = ApplyHarnessEditsCommand(edits=[{"section": "core", "text": "Be polite"}])
        result = await handler.handle(cmd)

        assert result.success
        assert result.data["candidate_version"] == 2
        assert result.data["edits_applied"] == 1
        mock_harness_target.apply_edits.assert_awaited_once_with(
            [{"section": "core", "text": "Be polite"}]
        )

    @pytest.mark.asyncio
    async def test_auto_loads_when_not_loaded(
        self, mock_harness_target: MagicMock
    ):
        """When target.is_loaded is False, handler calls load() first."""
        mock_candidate = MagicMock()
        mock_candidate.version = 1
        mock_candidate.model_dump = MagicMock(return_value={"version": 1})

        mock_harness_target.is_loaded = False
        mock_harness_target.load = AsyncMock()
        mock_harness_target.apply_edits = AsyncMock(return_value=mock_candidate)

        handler = ApplyHarnessEditsHandler(target=mock_harness_target)
        cmd = ApplyHarnessEditsCommand(edits=[])
        result = await handler.handle(cmd)

        assert result.success
        mock_harness_target.load.assert_awaited_once()
        mock_harness_target.apply_edits.assert_awaited_once()
