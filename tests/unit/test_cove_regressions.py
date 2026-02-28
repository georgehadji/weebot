"""Falsification regression tests for CoVe-identified adversarial bugs.

Each test is designed to FAIL if — and only if — the original bug is
reintroduced.  They are NOT general correctness tests; they target the
specific failure mode discovered through Chain-of-Verification analysis.

Bug map
-------
Fix #1  ResumableTask.__aexit__ double-exception masking  (state_manager.py)
Fix #2  Playwright process leak — missing stop() + race   (advanced_browser.py)
Fix #3  pyautogui blocking the asyncio event loop         (computer_use.py)
Fix #4  APScheduler double-execution race                 (scheduler.py)
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import weebot.tools.advanced_browser as _ab_mod
from weebot.scheduling.scheduler import ScheduledJob, SchedulingManager
from weebot.state_manager import ProjectStatus, ResumableTask, StateManager
from weebot.tools.computer_use import ComputerUseTool


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _tmp_db():
    """Return (db_path, tmpdir_path) for an isolated SQLite database."""
    d = tempfile.mkdtemp()
    return Path(d) / "test.db", Path(d)


def _cleanup(d: Path) -> None:
    try:
        shutil.rmtree(d)
    except Exception:
        pass


# ===========================================================================
# Fix #1 — ResumableTask.__aexit__ double-exception masking
#
# Original bug: save_state() raised inside __aexit__, and that new exception
# replaced the original exception from the task body, causing:
#   • permanent RUNNING status in SQLite (state never updated)
#   • the original error silently discarded
# ===========================================================================

class TestResumableTaskDoubleException:
    """save_state() is called in BOTH __aenter__ and __aexit__.  All tests
    use an 'aenter_complete' flag to allow the aenter calls to succeed and
    only fail the aexit calls, isolating the exact failure mode."""

    @staticmethod
    def _aexit_only_raiser(sm):
        """Return a save_state side-effect that raises only after __aenter__
        has completed (i.e., once the flag is set from inside the body)."""
        aenter_complete = [False]
        original = sm.save_state

        def side_effect(state):
            if aenter_complete[0]:
                raise OSError("DB_SAVE_FAILED")
            return original(state)

        return side_effect, aenter_complete

    @pytest.mark.asyncio
    async def test_original_exception_propagates_when_save_state_fails(self):
        """FALSIFIER: OSError from save_state must NOT replace the RuntimeError
        raised inside the task body.  If the bug returns, pytest.raises sees
        OSError ('DB_SAVE_FAILED') instead of RuntimeError ('ORIGINAL_ERROR')."""
        db, d = _tmp_db()
        try:
            sm = StateManager(db_path=str(db))
            sm.create_project("p1", "test")
            side_effect, flag = self._aexit_only_raiser(sm)
            with patch.object(sm, "save_state", side_effect=side_effect):
                with pytest.raises(RuntimeError, match="ORIGINAL_ERROR"):
                    async with ResumableTask(sm, "p1", "task1"):
                        flag[0] = True           # aenter done; aexit will fail
                        raise RuntimeError("ORIGINAL_ERROR")
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_end_sub_session_called_when_save_state_raises(self):
        """FALSIFIER: end_sub_session() must be called via the finally block
        even when save_state() fails.  Without the finally guard, sub-sessions
        accumulate as permanently open in RUNNING status."""
        db, d = _tmp_db()
        try:
            sm = StateManager(db_path=str(db))
            sm.create_project("p1", "test")
            side_effect, flag = self._aexit_only_raiser(sm)
            end_calls: list[str] = []

            def tracking_end(project_id, name, status="completed"):
                end_calls.append(status)    # record only; don't call original

            with patch.object(sm, "save_state", side_effect=side_effect):
                with patch.object(sm, "end_sub_session", side_effect=tracking_end):
                    try:
                        async with ResumableTask(sm, "p1", "task1"):
                            flag[0] = True
                    except Exception:
                        pass

            assert len(end_calls) >= 1, (
                "end_sub_session must be called even when save_state fails"
            )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_end_sub_session_status_failed_on_compound_failure(self):
        """FALSIFIER: Compound failure — body raises AND save_state raises.
        end_sub_session must still be called with status='failed', not silently
        lost.  Without the try/except + finally structure, this call is skipped."""
        db, d = _tmp_db()
        try:
            sm = StateManager(db_path=str(db))
            sm.create_project("p1", "test")
            side_effect, flag = self._aexit_only_raiser(sm)
            end_statuses: list[str] = []

            def tracking_end(project_id, name, status="completed"):
                end_statuses.append(status)

            with patch.object(sm, "save_state", side_effect=side_effect):
                with patch.object(sm, "end_sub_session", side_effect=tracking_end):
                    try:
                        async with ResumableTask(sm, "p1", "task1"):
                            flag[0] = True
                            raise ValueError("BODY_ERROR")
                    except (ValueError, OSError):
                        pass

            assert len(end_statuses) >= 1, "end_sub_session must always be called"
            assert end_statuses[0] == "failed", (
                f"status must be 'failed' when body raised, got: {end_statuses[0]!r}"
            )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_save_failure_does_not_propagate_when_body_succeeds(self):
        """FALSIFIER: A save_state() failure must NOT raise to the caller when
        the task body itself succeeded.  Without the try/except guard, the
        caller receives a spurious OSError even though the task completed."""
        db, d = _tmp_db()
        try:
            sm = StateManager(db_path=str(db))
            sm.create_project("p1", "test")
            side_effect, flag = self._aexit_only_raiser(sm)
            with patch.object(sm, "save_state", side_effect=side_effect):
                try:
                    async with ResumableTask(sm, "p1", "task1"):
                        flag[0] = True    # aenter done; aexit saves will fail
                        # body succeeds — no exception raised
                except OSError:
                    pytest.fail(
                        "save_state() failure must NOT propagate when body succeeded"
                    )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_from_body_still_propagates(self):
        """FALSIFIER: BaseException (KeyboardInterrupt) from the task body must
        propagate regardless of save_state outcome.  The except Exception guard
        must not accidentally swallow BaseException subclasses."""
        db, d = _tmp_db()
        try:
            sm = StateManager(db_path=str(db))
            sm.create_project("p1", "test")
            side_effect, flag = self._aexit_only_raiser(sm)
            with patch.object(sm, "save_state", side_effect=side_effect):
                with pytest.raises(KeyboardInterrupt):
                    async with ResumableTask(sm, "p1", "task1"):
                        flag[0] = True
                        raise KeyboardInterrupt
        finally:
            _cleanup(d)


# ===========================================================================
# Fix #2 — Playwright process leak + concurrent-close τ violation
#
# Original bug (process leak): _close_browser() never called
#   _playwright_instance.stop(), leaving Chromium alive after Python exited.
#
# τ violation (concurrent-close race): _playwright_instance = None was
#   AFTER the await, so if stop() raised, the global stayed non-None and
#   the atexit handler double-stopped the already-broken instance.
# ===========================================================================

class TestPlaywrightProcessLeak:

    @pytest.mark.asyncio
    async def test_close_browser_calls_playwright_stop(self):
        """FALSIFIER: _playwright_instance.stop() MUST be called in
        _close_browser().  Omitting it leaves a zombie Chromium subprocess."""
        mock_pw = AsyncMock()
        _ab_mod._playwright_instance = mock_pw
        try:
            await _ab_mod.AdvancedBrowserTool()._close_browser()
            mock_pw.stop.assert_called_once(), (
                "_playwright_instance.stop() must be called in _close_browser()"
            )
        finally:
            _ab_mod._playwright_instance = None

    @pytest.mark.asyncio
    async def test_close_browser_sets_instance_to_none(self):
        """FALSIFIER: After _close_browser(), the global must be None.
        If it stays non-None, the atexit handler double-stops on process exit."""
        _ab_mod._playwright_instance = AsyncMock()
        try:
            await _ab_mod.AdvancedBrowserTool()._close_browser()
            assert _ab_mod._playwright_instance is None, (
                "_playwright_instance must be None after _close_browser()"
            )
        finally:
            _ab_mod._playwright_instance = None

    @pytest.mark.asyncio
    async def test_close_browser_is_idempotent(self):
        """FALSIFIER: Calling _close_browser() twice must not raise.
        Concurrent agent 'close' actions both call this; the second must be
        a safe no-op, not an AttributeError on an already-None global."""
        tool = _ab_mod.AdvancedBrowserTool()
        await tool._close_browser()   # nothing to close
        await tool._close_browser()   # must not raise

    @pytest.mark.asyncio
    async def test_global_zeroed_before_await_when_stop_raises(self):
        """FALSIFIER: τ-violation guard — zero-out-first pattern.

        Original pattern:  if _playwright_instance: await ....stop(); global = None
        Problem: if stop() raises, 'global = None' is unreachable, so atexit
        still sees a non-None instance and calls stop() again.

        Conservative fix: global = None BEFORE await.  Verify by checking the
        global is None even when stop() raises.
        """
        mock_pw = AsyncMock()
        mock_pw.stop.side_effect = RuntimeError("playwright already stopped")
        _ab_mod._playwright_instance = mock_pw
        try:
            try:
                await _ab_mod.AdvancedBrowserTool()._close_browser()
            except Exception:
                pass   # stop() raising is allowed
            assert _ab_mod._playwright_instance is None, (
                "Global must be zeroed before await — "
                "stops atexit from double-calling stop() after a failed close"
            )
        finally:
            _ab_mod._playwright_instance = None

    @pytest.mark.asyncio
    async def test_all_globals_zeroed_before_respective_awaits(self):
        """FALSIFIER: The zero-out-first pattern must apply to ALL four globals,
        not just _playwright_instance.  If page.close() raises, _page must
        still be None so a retry does not double-close a corrupted page."""
        mock_page = AsyncMock()
        mock_page.close.side_effect = RuntimeError("page already closed")
        _ab_mod._page = mock_page
        _ab_mod._context = None
        _ab_mod._browser = None
        _ab_mod._playwright_instance = None
        try:
            try:
                await _ab_mod.AdvancedBrowserTool()._close_browser()
            except Exception:
                pass
            assert _ab_mod._page is None, (
                "_page must be None even when page.close() raises"
            )
        finally:
            _ab_mod._page = None

    def test_atexit_handler_stops_remaining_instance(self):
        """FALSIFIER: The atexit handler must call stop() on any instance that
        _close_browser() missed (crashes, SIGTERM, unhandled exceptions).
        If the handler is absent or does not call stop(), process exit leaks
        the Chromium subprocess."""
        mock_pw = MagicMock()
        mock_pw.stop = AsyncMock()
        _ab_mod._playwright_instance = mock_pw
        try:
            from weebot.tools.advanced_browser import _atexit_cleanup_playwright
            _atexit_cleanup_playwright()
            mock_pw.stop.assert_called_once()
            assert _ab_mod._playwright_instance is None
        finally:
            _ab_mod._playwright_instance = None


# ===========================================================================
# Fix #3 — pyautogui blocking the asyncio event loop
#
# Original bug: every pyautogui call (moveTo, click, write…) ran directly on
# the event-loop thread, freezing all other coroutines for its duration.
# Fix: all calls offloaded via asyncio.to_thread(); type action wrapped in
# asyncio.wait_for() with a dynamic proportional timeout.
# ===========================================================================

class TestPyautoguiEventLoopBlocking:

    @pytest.mark.asyncio
    async def test_move_mouse_offloaded_to_thread(self):
        """FALSIFIER: move_mouse must dispatch pyautogui.moveTo via
        asyncio.to_thread().  A direct call blocks the event loop."""
        tool = ComputerUseTool()
        offloaded: list[str] = []
        original = asyncio.to_thread

        async def spy(func, *args, **kwargs):
            offloaded.append(getattr(func, "__name__", str(func)))
            return await original(func, *args, **kwargs)

        with patch("asyncio.to_thread", side_effect=spy):
            with patch("pyautogui.moveTo"):
                await tool.execute(action="move_mouse", x=10, y=20)

        assert any("moveTo" in name for name in offloaded), (
            "move_mouse must use asyncio.to_thread() — direct call blocks event loop"
        )

    @pytest.mark.asyncio
    async def test_click_offloaded_to_thread(self):
        """FALSIFIER: click must dispatch via asyncio.to_thread()."""
        tool = ComputerUseTool()
        offloaded: list[str] = []
        original = asyncio.to_thread

        async def spy(func, *args, **kwargs):
            offloaded.append(getattr(func, "__name__", str(func)))
            return await original(func, *args, **kwargs)

        with patch("asyncio.to_thread", side_effect=spy):
            with patch("pyautogui.click"):
                await tool.execute(action="click", x=10, y=20)

        assert any("click" in name for name in offloaded), (
            "click must use asyncio.to_thread()"
        )

    @pytest.mark.asyncio
    async def test_type_action_uses_wait_for(self):
        """FALSIFIER: type action must wrap asyncio.to_thread() in
        asyncio.wait_for().  Without it, a hung pyautogui.write() permanently
        blocks the event loop with no escape hatch."""
        tool = ComputerUseTool()
        wait_for_timeouts: list[float] = []
        original_wf = asyncio.wait_for

        async def spy_wf(coro, timeout):
            wait_for_timeouts.append(timeout)
            return await original_wf(coro, timeout)

        with patch("asyncio.wait_for", side_effect=spy_wf):
            with patch("pyautogui.write"):
                await tool.execute(action="type", text="hello")

        assert wait_for_timeouts, (
            "type action must use asyncio.wait_for() — no timeout = permanent block risk"
        )

    @pytest.mark.asyncio
    async def test_type_returns_tool_error_on_timeout(self):
        """FALSIFIER: asyncio.TimeoutError must be caught and converted to a
        ToolResult(error=...).  If it propagates, the ReAct agent loop crashes
        with an unhandled exception instead of gracefully retrying."""
        tool = ComputerUseTool()

        async def instant_timeout(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError

        with patch("asyncio.wait_for", side_effect=instant_timeout):
            result = await tool.execute(action="type", text="hello")

        assert result.is_error, "TimeoutError must produce a ToolResult error, not propagate"
        assert "timed out" in result.error.lower(), (
            f"Error message must mention timeout, got: {result.error!r}"
        )

    @pytest.mark.asyncio
    async def test_type_timeout_proportional_to_text_length(self):
        """FALSIFIER: Timeout must grow with text length.
        A fixed timeout either starves long strings (false timeout) or allows
        runaway short-string executions.  Formula: max(10, len*interval*2)."""
        tool = ComputerUseTool()
        timeouts: list[float] = []
        original_wf = asyncio.wait_for

        async def spy_wf(coro, timeout):
            timeouts.append(timeout)
            return await original_wf(coro, timeout)

        with patch("asyncio.wait_for", side_effect=spy_wf):
            with patch("pyautogui.write"):
                # Short text — hits the 10 s floor
                await tool.execute(action="type", text="hi", interval=0.05)
                # Long text — proportional timeout (max(10, 300*0.05*2) = 30 s)
                await tool.execute(action="type", text="x" * 300, interval=0.05)

        assert len(timeouts) == 2
        assert timeouts[0] >= 10.0, f"Short-text timeout too small: {timeouts[0]}"
        assert timeouts[1] > timeouts[0], (
            f"Long-text timeout ({timeouts[1]}) must exceed short-text ({timeouts[0]})"
        )

    @pytest.mark.asyncio
    async def test_move_mouse_duration_passed_as_keyword(self):
        """FALSIFIER: Exact regression guard for the duration=0.25 keyword fix.

        The bug was: asyncio.to_thread(moveTo, x, y, 0.25) — 0.25 was passed
        positionally.  Although pyautogui.moveTo accepts it positionally too,
        mock assertions require the keyword form.  This test permanently
        enforces the keyword-argument contract."""
        tool = ComputerUseTool()
        with patch("pyautogui.moveTo") as mock_move:
            await tool.execute(action="move_mouse", x=42, y=99)
        mock_move.assert_called_once_with(42, 99, duration=0.25)


# ===========================================================================
# Fix #4 — APScheduler double-execution race
#
# Original risk: APScheduler could fire the same job during the update_job()
# remove_job → add_job window, and no in-process guard existed against
# concurrent _execute_job() calls for the same job_id.
#
# Fix: max_instances=1 + coalesce=True in add_job(), plus a _running_jobs
# set as a secondary execution guard inside _execute_job().
# ===========================================================================

class TestSchedulerExecutionGuard:

    @pytest.mark.asyncio
    async def test_add_job_max_instances_1(self):
        """FALSIFIER: max_instances=1 must be explicitly passed to add_job().
        Without it, APScheduler may run multiple instances of the same job
        concurrently during trigger catch-up, causing duplicate side-effects."""
        db, d = _tmp_db()
        try:
            mgr = SchedulingManager(db_path=db)
            with patch.object(mgr.scheduler, "add_job") as mock_add:
                await mgr._schedule_job(ScheduledJob(
                    job_id="j1", name="Test",
                    trigger_type="interval", trigger_config={"seconds": 60},
                    callable_name="test",
                ))
            kw = mock_add.call_args.kwargs
            assert kw.get("max_instances") == 1, (
                f"max_instances must be 1, got {kw.get('max_instances')!r}"
            )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_add_job_coalesce_true(self):
        """FALSIFIER: coalesce=True must be explicitly passed to add_job().
        Without it, a suspend/resume cycle fires N missed executions instead
        of one catch-up run — N-fold duplicate side-effects."""
        db, d = _tmp_db()
        try:
            mgr = SchedulingManager(db_path=db)
            with patch.object(mgr.scheduler, "add_job") as mock_add:
                await mgr._schedule_job(ScheduledJob(
                    job_id="j1", name="Test",
                    trigger_type="interval", trigger_config={"seconds": 60},
                    callable_name="test",
                ))
            kw = mock_add.call_args.kwargs
            assert kw.get("coalesce") is True, (
                f"coalesce must be True, got {kw.get('coalesce')!r}"
            )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_running_jobs_guard_skips_duplicate_invocation(self):
        """FALSIFIER: If _running_jobs check is removed, _execute_job() proceeds
        to get_job() for an already-executing job — double execution."""
        db, d = _tmp_db()
        try:
            mgr = SchedulingManager(db_path=db)
            # Pre-populate the set to simulate a job already executing
            mgr._running_jobs.add("ghost_job")
            get_job_reached = False
            original_get = mgr.get_job

            def spy_get(job_id):
                nonlocal get_job_reached
                get_job_reached = True
                return original_get(job_id)

            mgr.get_job = spy_get
            await mgr._execute_job("ghost_job")
            assert not get_job_reached, (
                "get_job() must NOT be reached when job_id is in _running_jobs — "
                "execution guard not working"
            )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_running_jobs_cleared_after_success(self):
        """FALSIFIER: If job_id is not removed from _running_jobs after success,
        every subsequent trigger invocation is silently skipped — the job
        permanently stalls after its first execution."""
        db, d = _tmp_db()
        try:
            mgr = SchedulingManager(db_path=db)
            call_count = [0]

            def counter():
                call_count[0] += 1

            mgr.register_callable("counter", counter)
            await mgr.create_job(
                job_id="j1", name="Counter",
                trigger_type="cron", trigger_config={},
                callable_name="counter",
            )

            await mgr._execute_job("j1")
            assert "j1" not in mgr._running_jobs, (
                "job_id must be removed from _running_jobs after success"
            )
            await mgr._execute_job("j1")   # would be skipped if set not cleared
            assert call_count[0] == 2, (
                f"Job ran {call_count[0]} times; expected 2 (second run was skipped)"
            )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_running_jobs_cleared_after_failure(self):
        """FALSIFIER: If job_id stays in _running_jobs after a failure, the job
        can never run again — permanent zombie state that silently loses work."""
        db, d = _tmp_db()
        try:
            mgr = SchedulingManager(db_path=db)
            call_count = [0]

            def fail_then_succeed():
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("first run fails intentionally")

            mgr.register_callable("fn", fail_then_succeed)
            await mgr.create_job(
                job_id="j2", name="Fail-then-succeed",
                trigger_type="cron", trigger_config={},
                callable_name="fn",
            )

            await mgr._execute_job("j2")   # first call — fails
            assert "j2" not in mgr._running_jobs, (
                "job_id must be cleared from _running_jobs even after failure"
            )
            await mgr._execute_job("j2")   # second call — must NOT be skipped
            assert call_count[0] == 2, (
                "Job must run again after failure — second call was blocked by stale guard"
            )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_running_jobs_initialized_as_empty_set(self):
        """FALSIFIER: _running_jobs must exist, be a set, and be empty on init.
        A missing attribute causes AttributeError on the first job execution;
        wrong type causes silent guard bypass."""
        db, d = _tmp_db()
        try:
            mgr = SchedulingManager(db_path=db)
            assert hasattr(mgr, "_running_jobs"), (
                "_running_jobs attribute is missing from SchedulingManager"
            )
            assert isinstance(mgr._running_jobs, set), (
                f"_running_jobs must be a set, got: {type(mgr._running_jobs)}"
            )
            assert len(mgr._running_jobs) == 0, (
                "_running_jobs must be empty on initialization"
            )
        finally:
            _cleanup(d)

    @pytest.mark.asyncio
    async def test_concurrent_invocations_execute_exactly_once(self):
        """FALSIFIER: Black-swan — two _execute_job coroutines for the same
        job_id launched concurrently via asyncio.gather().

        asyncio is cooperative: the first coroutine adds job_id to
        _running_jobs synchronously (before any await), so when it yields at
        'await result', the second coroutine's guard check sees the set and
        returns immediately.  Execution count must be 1, not 2."""
        db, d = _tmp_db()
        try:
            mgr = SchedulingManager(db_path=db)
            execution_count = [0]

            async def slow_callable():
                execution_count[0] += 1
                await asyncio.sleep(0)   # yield to let the concurrent call attempt

            mgr.register_callable("slow", slow_callable)
            await mgr.create_job(
                job_id="j3", name="Concurrent",
                trigger_type="cron", trigger_config={},
                callable_name="slow",
            )

            await asyncio.gather(
                mgr._execute_job("j3"),
                mgr._execute_job("j3"),
            )

            assert execution_count[0] == 1, (
                f"Job executed {execution_count[0]} times with concurrent invocations; "
                "must execute exactly once — execution guard not working"
            )
        finally:
            _cleanup(d)
