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
