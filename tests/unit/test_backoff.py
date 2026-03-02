"""Unit tests for exponential backoff retry utility."""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from weebot.utils.backoff import RetryWithBackoff, BackoffConfig


class TestBackoffConfig:
    def test_default_delays(self):
        cfg = BackoffConfig()
        assert cfg.delays == [1, 2, 4, 8, 15, 30, 60]

    def test_max_delay_capped(self):
        cfg = BackoffConfig(delays=[1, 2, 4], max_delay=3)
        assert all(d <= 3 for d in cfg.delays)

    def test_custom_delays(self):
        cfg = BackoffConfig(delays=[0.1, 0.2, 0.4])
        assert cfg.delays == [0.1, 0.2, 0.4]

    def test_max_delay_none_unchanged(self):
        cfg = BackoffConfig(delays=[5, 10, 20], max_delay=None)
        assert cfg.delays == [5, 10, 20]


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self):
        mock_fn = AsyncMock(return_value="ok")
        retry = RetryWithBackoff(BackoffConfig(delays=[0.01]))
        result = await retry.call(mock_fn)
        assert result == "ok"
        assert mock_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        mock_fn = AsyncMock(side_effect=[Exception("fail"), Exception("fail"), "ok"])
        retry = RetryWithBackoff(BackoffConfig(delays=[0.01, 0.01, 0.01]))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await retry.call(mock_fn)
        assert result == "ok"
        assert mock_fn.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        mock_fn = AsyncMock(side_effect=Exception("always fails"))
        retry = RetryWithBackoff(BackoffConfig(delays=[0.01]))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(Exception, match="always fails"):
                await retry.call(mock_fn)

    @pytest.mark.asyncio
    async def test_resets_delay_index_after_success(self):
        calls: list = []

        async def fn():
            calls.append(1)
            if len(calls) < 3:
                raise Exception("not yet")
            return "done"

        retry = RetryWithBackoff(BackoffConfig(delays=[0.01, 0.01, 0.01]))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await retry.call(fn)
        assert retry._delay_index == 0     # reset after success

    @pytest.mark.asyncio
    async def test_passes_args_to_fn(self):
        async def adder(a, b):
            return a + b

        retry = RetryWithBackoff(BackoffConfig(delays=[0.01]))
        result = await retry.call(adder, 3, 4)
        assert result == 7

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        """A non-retryable exception should be re-raised on the first attempt."""
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        cfg = BackoffConfig(
            delays=[0.01, 0.01, 0.01],
            retryable=lambda exc: not isinstance(exc, ValueError),
        )
        retry = RetryWithBackoff(cfg)
        with pytest.raises(ValueError, match="not retryable"):
            await retry.call(fn)
        assert call_count == 1  # zero retries

    @pytest.mark.asyncio
    async def test_retryable_predicate_retries_matching_errors(self):
        """A retryable exception should trigger the normal retry loop."""
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("retryable")
            return "ok"

        cfg = BackoffConfig(
            delays=[0.01, 0.01, 0.01],
            retryable=lambda exc: isinstance(exc, ConnectionError),
        )
        retry = RetryWithBackoff(cfg)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await retry.call(fn)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_jitter_delays_within_expected_range(self):
        """Actual sleep delay must be in [base, base * (1 + jitter)]."""
        slept: list[float] = []

        async def capture_sleep(delay: float) -> None:
            slept.append(delay)

        cfg = BackoffConfig(delays=[1.0], jitter=0.5)
        retry = RetryWithBackoff(cfg)

        async def always_fails():
            raise RuntimeError("fail")

        with patch("asyncio.sleep", side_effect=capture_sleep):
            with pytest.raises(RuntimeError):
                await retry.call(always_fails)

        assert slept, "sleep should have been called"
        assert slept[0] >= 1.0
        assert slept[0] <= 1.0 * (1 + 0.5)
