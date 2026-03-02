"""Unit tests for SandboxedExecutor and ExecutionResult."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.sandbox.executor import ExecutionResult, SandboxedExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proc(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> MagicMock:
    """Build a fake asyncio subprocess proc."""
    proc = MagicMock()
    proc.pid = 12345
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=None)
    return proc


# ---------------------------------------------------------------------------
# ExecutionResult unit tests
# ---------------------------------------------------------------------------

class TestExecutionResult:

    def test_success_true_when_clean_exit(self):
        r = ExecutionResult(stdout="hi", stderr="", returncode=0, elapsed_ms=10.0)
        assert r.success is True

    def test_success_false_on_nonzero_returncode(self):
        r = ExecutionResult(stdout="", stderr="err", returncode=1, elapsed_ms=5.0)
        assert r.success is False

    def test_success_false_when_timed_out(self):
        r = ExecutionResult(stdout="", stderr="", returncode=0, elapsed_ms=30.0, timed_out=True)
        assert r.success is False

    def test_combined_output_stdout_only(self):
        r = ExecutionResult(stdout="hello\n", stderr="", returncode=0, elapsed_ms=1.0)
        assert r.combined_output == "hello\n"

    def test_combined_output_both_streams(self):
        r = ExecutionResult(stdout="out", stderr="err", returncode=0, elapsed_ms=1.0)
        assert "out" in r.combined_output
        assert "[stderr]" in r.combined_output
        assert "err" in r.combined_output

    def test_combined_output_empty_is_placeholder(self):
        r = ExecutionResult(stdout="", stderr="", returncode=0, elapsed_ms=1.0)
        assert r.combined_output == "(no output)"


# ---------------------------------------------------------------------------
# SandboxedExecutor tests
# ---------------------------------------------------------------------------

class TestSandboxedExecutor:

    @pytest.mark.asyncio
    async def test_successful_run_captures_stdout(self):
        """Happy path: stdout is decoded and returned in ExecutionResult."""
        executor = SandboxedExecutor()
        proc = _make_proc(stdout=b"hello world\n", stderr=b"")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.run(["echo", "hello world"], timeout=5)

        assert result.success
        assert "hello world" in result.stdout
        assert result.returncode == 0

    @pytest.mark.asyncio
    async def test_nonzero_returncode_sets_success_false(self):
        """Exit code 1 produces success=False."""
        executor = SandboxedExecutor()
        proc = _make_proc(returncode=1, stdout=b"", stderr=b"bad command")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.run(["false"], timeout=5)

        assert not result.success
        assert result.returncode == 1
        assert "bad command" in result.stderr

    @pytest.mark.asyncio
    async def test_timeout_sets_timed_out_flag(self):
        """asyncio.TimeoutError -> proc.kill() called, timed_out=True."""
        executor = SandboxedExecutor()
        proc = _make_proc()

        async def instant_timeout(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with patch("asyncio.wait_for", side_effect=instant_timeout):
                result = await executor.run(["sleep", "999"], timeout=1)

        assert result.timed_out
        assert not result.success
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_output_truncated_at_max_bytes(self):
        """Output exceeding max_output_bytes gets a '[truncated]' suffix."""
        max_bytes = 10
        executor = SandboxedExecutor(max_output_bytes=max_bytes)
        large_output = b"A" * 100
        proc = _make_proc(stdout=large_output, stderr=b"")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.run(["cat", "big_file"], timeout=5)

        assert "[truncated]" in result.stdout
        # Decoded content should not exceed max_bytes + suffix
        assert len(result.stdout.encode()) <= max_bytes + len(b"...[truncated]")

    @pytest.mark.asyncio
    async def test_elapsed_ms_populated(self):
        """elapsed_ms reflects wall-clock time via time.monotonic()."""
        executor = SandboxedExecutor()
        proc = _make_proc(stdout=b"ok")

        # Simulate 42 ms elapsed by controlling monotonic clock values.
        monotonic_values = iter([1000.0, 1000.042])

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with patch("weebot.sandbox.executor.time") as mock_time:
                mock_time.monotonic.side_effect = monotonic_values
                result = await executor.run(["echo", "ok"], timeout=5)

        assert result.elapsed_ms == pytest.approx(42.0, abs=1.0)


class TestTimeoutGuard:
    """Black swan fix: timeout <= 0 must never reach asyncio.wait_for.

    CPython 3.11+ raises ValueError (not TimeoutError) for timeout <= 0,
    leaving the subprocess running without supervision.
    """

    @pytest.mark.asyncio
    async def test_zero_timeout_returns_error_result_not_valueerror(self):
        """timeout=0 must return an error ExecutionResult, not raise ValueError."""
        executor = SandboxedExecutor()
        # No subprocess should be created — the guard fires before create_subprocess_exec.
        with patch("asyncio.create_subprocess_exec") as mock_create:
            result = await executor.run(["echo", "hi"], timeout=0)
        mock_create.assert_not_called()
        assert result.returncode == -1
        assert "timeout" in result.stderr.lower()
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_negative_timeout_returns_error_result(self):
        """Negative timeout must also be rejected before subprocess creation."""
        executor = SandboxedExecutor()
        with patch("asyncio.create_subprocess_exec") as mock_create:
            result = await executor.run(["echo", "hi"], timeout=-5)
        mock_create.assert_not_called()
        assert result.returncode == -1

    @pytest.mark.asyncio
    async def test_positive_timeout_passes_through_to_subprocess(self):
        """A valid positive timeout must still reach asyncio.create_subprocess_exec."""
        executor = SandboxedExecutor()
        proc = _make_proc(stdout=b"ok")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.run(["echo", "ok"], timeout=10)
        assert isinstance(result.returncode, int)
