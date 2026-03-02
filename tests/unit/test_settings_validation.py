"""Tests for WeebotSettings field validators — timeout and output-byte bounds.

Black swan: BASH_TIMEOUT=0 in .env causes asyncio.wait_for to raise ValueError
(not TimeoutError) in CPython 3.11+, leaking a zombie subprocess.  The validators
here catch that at settings-load time with a clear, actionable message.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from weebot.config.settings import WeebotSettings


# Minimal valid settings that won't hit API-key validation.
_BASE = dict(anthropic_api_key="test-key")


class TestTimeoutValidators:

    def test_bash_timeout_positive_is_accepted(self):
        s = WeebotSettings(**_BASE, bash_timeout=60)
        assert s.bash_timeout == 60

    def test_python_timeout_positive_is_accepted(self):
        s = WeebotSettings(**_BASE, python_timeout=120)
        assert s.python_timeout == 120

    def test_bash_timeout_zero_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            WeebotSettings(**_BASE, bash_timeout=0)
        assert "bash_timeout" in str(exc_info.value) or "Timeout" in str(exc_info.value)

    def test_bash_timeout_negative_raises(self):
        with pytest.raises(ValidationError):
            WeebotSettings(**_BASE, bash_timeout=-1)

    def test_python_timeout_zero_raises(self):
        with pytest.raises(ValidationError):
            WeebotSettings(**_BASE, python_timeout=0)

    def test_python_timeout_negative_raises(self):
        with pytest.raises(ValidationError):
            WeebotSettings(**_BASE, python_timeout=-99)


class TestMaxOutputBytesValidator:

    def test_valid_max_output_bytes_accepted(self):
        s = WeebotSettings(**_BASE, sandbox_max_output_bytes=65_536)
        assert s.sandbox_max_output_bytes == 65_536

    def test_minimum_boundary_1024_accepted(self):
        s = WeebotSettings(**_BASE, sandbox_max_output_bytes=1024)
        assert s.sandbox_max_output_bytes == 1024

    def test_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            WeebotSettings(**_BASE, sandbox_max_output_bytes=512)

    def test_zero_raises(self):
        with pytest.raises(ValidationError):
            WeebotSettings(**_BASE, sandbox_max_output_bytes=0)

    def test_negative_raises(self):
        with pytest.raises(ValidationError):
            WeebotSettings(**_BASE, sandbox_max_output_bytes=-1)
