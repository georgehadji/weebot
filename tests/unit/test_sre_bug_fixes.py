"""
Regression tests for SRE fixes.

Each test is labelled with the bug ID it covers and includes:
  - A "fails without patch" assertion comment
  - The expected post-patch behaviour

Run with:  pytest tests/unit/test_sre_bug_fixes.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ════════════════════════════════════════════════════════════════
# BUG-001 — ValidationRunner.validate() bootstrap always-reject
# ════════════════════════════════════════════════════════════════

class TestBug001ValidationRunnerBootstrap:
    """BUG-001: baseline_score=None used to make passed always False."""

    @pytest.fixture
    def runner(self):
        from weebot.application.services.validation_runner import ValidationRunner

        async def _scorer(session):
            return 0.75  # stable score for all tasks

        async def _factory(session):
            class FakeFlow:
                _session = session
                async def run(self, *a, **kw):
                    return
                    yield  # make it an async generator
                def is_done(self):
                    return True
            return FakeFlow()

        task_runner = MagicMock()
        return ValidationRunner(
            task_runner=task_runner,
            flow_factory=_factory,
            scoring_fn=_scorer,
        )

    @pytest.mark.asyncio
    async def test_bootstrap_passes_when_baseline_none(self, runner):
        """ID: BUG001-R01
        Pre-patch: passed=False always when baseline_score=None (self-comparison).
        Post-patch: passed=True for any positive candidate score.
        """
        result = await runner.validate(
            candidate_content="# skill",
            validation_task_ids=[],   # no tasks → candidate_score=0.0
            baseline_score=None,
        )
        # Empty task list → skipped with passed=True
        assert result.passed is True, "Bootstrap with no tasks must always pass"

    @pytest.mark.asyncio
    async def test_bootstrap_with_positive_score_passes(self):
        """ID: BUG001-R02
        Pre-patch: 0.75 > 0.75 = False.
        Post-patch: 0.75 > -1.0 = True.
        """
        from weebot.application.services.validation_runner import ValidationRunner

        calls = []

        async def _scorer(session):
            return 0.75

        async def _factory(session):
            class FakeFlow:
                _session = session
                async def run(self, prompt):
                    if False:
                        yield
            return FakeFlow()

        runner = ValidationRunner(
            task_runner=MagicMock(),
            flow_factory=_factory,
            scoring_fn=_scorer,
        )
        # Patch asyncio.gather so tasks run synchronously in test
        with patch("asyncio.gather", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = [0.75]
            result = await runner.validate(
                candidate_content="# skill",
                validation_task_ids=["task1"],
                baseline_score=None,
            )
        assert result.passed is True
        assert result.current_score == -1.0

    @pytest.mark.asyncio
    async def test_explicit_baseline_still_works(self):
        """ID: BUG001-R03 — existing non-bootstrap path unchanged."""
        from weebot.application.services.validation_runner import ValidationRunner

        runner = ValidationRunner(
            task_runner=MagicMock(),
            flow_factory=MagicMock(),
            scoring_fn=AsyncMock(return_value=0.60),
        )
        with patch("asyncio.gather", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = [0.60]
            result = await runner.validate(
                candidate_content="# skill",
                validation_task_ids=["t"],
                baseline_score=0.80,   # higher baseline → should reject
            )
        assert result.passed is False
        assert result.current_score == 0.80

    @pytest.mark.asyncio
    async def test_tie_still_rejected(self):
        """ID: BUG001-R04 — paper §3.5: ties rejected even after fix."""
        from weebot.application.services.validation_runner import ValidationRunner

        runner = ValidationRunner(
            task_runner=MagicMock(),
            flow_factory=MagicMock(),
            scoring_fn=AsyncMock(return_value=0.70),
        )
        with patch("asyncio.gather", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = [0.70]
            result = await runner.validate(
                candidate_content="# skill",
                validation_task_ids=["t"],
                baseline_score=0.70,  # exact tie
            )
        assert result.passed is False


# ════════════════════════════════════════════════════════════════
# BUG-002 — ConnectionPool acquire_write() race + no rollback
# ════════════════════════════════════════════════════════════════

class TestBug002ConnectionPoolWriteLock:
    """BUG-002: concurrent writers shared uncommitted transaction; no rollback."""

    @pytest.fixture
    def pool(self, tmp_path):
        from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool
        return SQLiteConnectionPool(
            db_path=tmp_path / "test.db",
            max_read_connections=2,
        )

    @pytest.mark.asyncio
    async def test_write_lock_serialises_concurrent_writes(self, pool):
        """ID: BUG002-R01
        Pre-patch: two coroutines could share _write_conn simultaneously.
        Post-patch: _write_lock ensures sequential access.
        """
        await pool.initialize()
        async with pool.acquire_write() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS t (id TEXT PRIMARY KEY, v TEXT)"
            )

        order = []

        async def write_a():
            async with pool.acquire_write() as conn:
                order.append("A-start")
                await asyncio.sleep(0.01)   # yield to let B try to enter
                await conn.execute("INSERT INTO t VALUES ('a', 'A')")
                order.append("A-end")

        async def write_b():
            await asyncio.sleep(0.001)   # start slightly after A
            async with pool.acquire_write() as conn:
                order.append("B-start")
                await conn.execute("INSERT INTO t VALUES ('b', 'B')")
                order.append("B-end")

        await asyncio.gather(write_a(), write_b())
        # B-start must not appear between A-start and A-end (would be without lock)
        a_start = order.index("A-start")
        a_end = order.index("A-end")
        b_start = order.index("B-start")
        assert not (a_start < b_start < a_end), (
            "B must not interleave with A under the write lock"
        )
        await pool.close()

    @pytest.mark.asyncio
    async def test_rollback_on_exception_leaves_clean_state(self, pool):
        """ID: BUG002-R02
        Pre-patch: exception in write context left transaction open; next writer
        could commit partial work from failed writer.
        Post-patch: explicit rollback on exception.
        """
        await pool.initialize()
        async with pool.acquire_write() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS t (id TEXT PRIMARY KEY)"
            )

        # First write: fails
        with pytest.raises(Exception):
            async with pool.acquire_write() as conn:
                await conn.execute("INSERT INTO t VALUES ('x')")
                raise RuntimeError("intentional failure")

        # Second write: must succeed cleanly (no uncommitted junk from first)
        async with pool.acquire_write() as conn:
            await conn.execute("INSERT INTO t VALUES ('y')")

        rows = await pool.execute_read("SELECT * FROM t")
        ids = [r[0] for r in rows]
        assert "y" in ids, "Clean write after exception must persist"
        assert "x" not in ids, "Rolled-back row must not appear"
        await pool.close()


# ════════════════════════════════════════════════════════════════
# BUG-003 — CircuitBreaker sleeps inside asyncio.Lock
# ════════════════════════════════════════════════════════════════

class TestBug003CircuitBreakerSleepOutsideLock:
    """BUG-003: asyncio.sleep inside _lock starved all concurrent callers."""

    @pytest.mark.asyncio
    async def test_other_entities_not_blocked_during_stagger(self):
        """ID: BUG003-R01
        Pre-patch: stagger sleep held _lock; model-B evaluate() could not run
        until model-A's stagger completed.
        Post-patch: stagger is outside the lock; model-B proceeds immediately.
        """
        from weebot.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.01,   # very short for test speed
            jitter_percent=0.0,
            enable_stagger=True,
        )

        # Trip model-A breaker
        await cb.record_failure("model-a")

        await asyncio.sleep(0.02)   # let cooldown elapse

        timeline = []

        async def probe_a():
            with patch.object(cb, "_maybe_stagger_probe",
                               new_callable=AsyncMock) as mock_stagger:
                async def slow_stagger():
                    timeline.append("stagger-start")
                    await asyncio.sleep(0.05)
                    timeline.append("stagger-end")
                mock_stagger.side_effect = slow_stagger
                result = await cb.evaluate("model-a")
                timeline.append("a-done")

        async def probe_b():
            await asyncio.sleep(0.01)   # start after A begins
            result = await cb.evaluate("model-b")   # model-b is CLOSED
            timeline.append("b-done")

        await asyncio.gather(probe_a(), probe_b())

        # b-done must appear BEFORE stagger-end (B was not blocked by A's stagger)
        assert timeline.index("b-done") < timeline.index("stagger-end"), (
            "model-b must not be blocked by model-a's stagger"
        )

    @pytest.mark.asyncio
    async def test_evaluate_still_transitions_to_half_open(self):
        """ID: BUG003-R02 — functional regression: stagger outside lock must
        still result in HALF_OPEN transition."""
        from weebot.core.circuit_breaker import CircuitBreaker, BreakerState

        cb = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.01,
            jitter_percent=0.0,
            enable_stagger=False,   # no stagger for speed
        )
        await cb.record_failure("m")
        await asyncio.sleep(0.02)
        result = await cb.evaluate("m")
        assert result.state == BreakerState.HALF_OPEN
        assert result.allowed is True


# ════════════════════════════════════════════════════════════════
# BUG-004 — Session._memory_index reset on model_copy
# ════════════════════════════════════════════════════════════════

class TestBug004SessionMemoryIndexPreserved:
    """BUG-004: _memory_index wiped on every add_event(); O(1) path unusable."""

    def _make_session(self):
        from weebot.domain.models.session import Session, SessionContext
        return Session(
            id="s1",
            user_id="u",
            agent_id="a",
            context=SessionContext(),
        )

    def test_memory_index_survives_add_event(self):
        """ID: BUG004-R01
        Pre-patch: _memory_index cleared after each add_event().
        Post-patch: accumulated index preserved.
        """
        from weebot.domain.models.event import PlanEvent, StepEvent
        from weebot.domain.models.plan import Plan, PlanStatus

        session = self._make_session()
        plan = Plan(title="t", steps=[], status=PlanStatus.CREATED)
        session = session.add_event(PlanEvent(plan=plan))
        session = session.add_event(StepEvent(step_id="s1", description="x"))

        # Pre-patch: plan_indices would be empty after second add_event()
        plan_indices = session._memory_index._index.get("plan", [])
        assert len(plan_indices) == 1, (
            "PlanEvent index must survive subsequent add_event() calls"
        )

    def test_get_last_plan_uses_index_not_fallback(self):
        """ID: BUG004-R02 — functional: get_last_plan() returns correct plan."""
        from weebot.domain.models.event import PlanEvent, MessageEvent
        from weebot.domain.models.plan import Plan, PlanStatus

        session = self._make_session()
        plan = Plan(title="my-plan", steps=[], status=PlanStatus.CREATED)
        session = session.add_event(PlanEvent(plan=plan))
        # Add several non-plan events afterwards
        for i in range(5):
            session = session.add_event(
                MessageEvent(role="assistant", message=f"msg {i}")
            )

        result = session.get_last_plan()
        assert result is not None
        assert result.title == "my-plan"

    def test_copy_is_independent(self):
        """ID: BUG004-R03 — copy() must not share deque references."""
        from weebot.domain.services.session_memory import SessionMemory
        from weebot.domain.models.event import MessageEvent

        mem = SessionMemory()
        event = MessageEvent(role="user", message="hi")
        mem.index_event(0, event)

        copy = mem.copy()
        # Modify copy's index — original must be unaffected
        copy._index["message"].append(99)

        assert 99 not in mem._index["message"], (
            "copy() must produce independent deques"
        )


# ════════════════════════════════════════════════════════════════
# BUG-005 — Double event publication in TaskRunner
# ════════════════════════════════════════════════════════════════

class TestBug005NoDoublePublish:
    """BUG-005: events published by flow._emit() were re-published by TaskRunner."""

    @pytest.mark.asyncio
    async def test_event_published_once_when_flow_has_bus(self):
        """ID: BUG005-R01
        Pre-patch: every event published twice (flow + runner).
        Post-patch: event published once (flow only).
        """
        from weebot.domain.models.event import MessageEvent, DoneEvent
        from weebot.domain.models.session import Session, SessionContext
        from weebot.application.services.task_runner import TaskRunner

        event_bus = AsyncMock()
        state_repo = AsyncMock()
        state_repo.load_session = AsyncMock(return_value=Session(
            id="sess",
            user_id="u",
            agent_id="a",
            context=SessionContext(last_prompt="hello"),
        ))
        state_repo.save_session = AsyncMock()

        msg_event = MessageEvent(role="assistant", message="hi")

        class FakeFlow:
            _event_bus = event_bus   # flow HAS its own bus
            _session = Session(id="sess", user_id="u", agent_id="a",
                               context=SessionContext())

            async def run(self, prompt):
                yield msg_event

            def is_done(self):
                return True

        runner = TaskRunner(state_repo=state_repo, event_bus=event_bus)
        await runner._run_flow("sess", FakeFlow())

        # Count how many times the message event was published
        publish_calls = [
            call for call in event_bus.publish.call_args_list
            if call.args and call.args[0] == msg_event
        ]
        assert len(publish_calls) == 0, (
            "TaskRunner must NOT re-publish events already published by flow._emit()"
        )

    @pytest.mark.asyncio
    async def test_event_published_by_runner_when_flow_has_no_bus(self):
        """ID: BUG005-R02 — fallback: TaskRunner publishes when flow has no bus."""
        from weebot.domain.models.event import MessageEvent
        from weebot.domain.models.session import Session, SessionContext
        from weebot.application.services.task_runner import TaskRunner

        event_bus = AsyncMock()
        state_repo = AsyncMock()
        state_repo.load_session = AsyncMock(return_value=Session(
            id="sess", user_id="u", agent_id="a",
            context=SessionContext(last_prompt="go"),
        ))
        state_repo.save_session = AsyncMock()

        msg_event = MessageEvent(role="assistant", message="hi")

        class FakeFlowNoBus:
            _event_bus = None   # NO bus on this flow
            _session = Session(id="sess", user_id="u", agent_id="a",
                               context=SessionContext())

            async def run(self, prompt):
                yield msg_event

            def is_done(self):
                return True

        runner = TaskRunner(state_repo=state_repo, event_bus=event_bus)
        await runner._run_flow("sess", FakeFlowNoBus())

        publish_calls = [
            call for call in event_bus.publish.call_args_list
            if call.args and call.args[0] == msg_event
        ]
        assert len(publish_calls) == 1, (
            "TaskRunner must publish once when flow has no event_bus"
        )
