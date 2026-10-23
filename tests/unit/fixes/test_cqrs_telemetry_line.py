"""The CQRS telemetry line reports only what it knows.

It printed "Model: unknown, Tokens: 0" on every command (seen on every line of
the 2026-10-23 smoke run): no handler returns `tokens_used` / `model_used`, so
it could never be right. Model and token cost come from the LLMCallCompleted
events (W4.1); this line keeps the duration.
"""

from __future__ import annotations

import logging

import pytest

from weebot.application.cqrs.base import Command, CommandResult
from weebot.application.cqrs.behaviors.telemetry import TelemetryBehavior


class _Cmd(Command):
    pass


@pytest.mark.asyncio
async def test_the_line_claims_no_model_or_tokens(caplog):
    async def _next():
        return CommandResult(success=True, data={"plan": "x"})

    with caplog.at_level(logging.INFO, logger="weebot.telemetry"):
        await TelemetryBehavior().handle(_Cmd(), _next)
    line = caplog.messages[-1]
    assert "_Cmd took" in line and "Model:" not in line and "Tokens:" not in line
