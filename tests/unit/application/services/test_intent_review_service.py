"""IntentReviewService timeout (remaining-fix plan A6).

The real run of 2026-10-22 logged "IntentReview failed for <id>:" with nothing
after the colon on every run: the hard-coded 5 s timeout fired on a thinking
model, and `str(TimeoutError())` is empty. It still fails open (NOT_READY).
"""

from __future__ import annotations

import asyncio
import logging

from weebot.application.services.intent_review_service import IntentReviewService
from weebot.config.settings import get_settings
from weebot.domain.models.idea_contract import IdeaContract, IdeaSource
from weebot.domain.models.intent_review import IntentVerdict


class _SlowLLM:
    async def chat(self, **_kwargs):
        await asyncio.sleep(1)


def _contract() -> IdeaContract:
    return IdeaContract(title="t", prompt="do x", source=IdeaSource.USER_PROMPT)


async def test_a_timeout_is_logged_by_name_and_fails_open(caplog):
    with caplog.at_level(logging.WARNING):
        review = await IntentReviewService(_SlowLLM(), timeout=0.01).review(_contract())
    assert review.verdict == IntentVerdict.NOT_READY
    assert "timed out after" in caplog.text


def test_the_timeout_is_a_setting(monkeypatch):
    assert get_settings().intent_review_timeout_s == 30.0
    get_settings.cache_clear()
    monkeypatch.setenv("WEEBOT_INTENT_REVIEW_TIMEOUT_S", "12")
    assert get_settings().intent_review_timeout_s == 12.0


def test_the_service_defaults_to_the_setting(monkeypatch):
    monkeypatch.setenv("WEEBOT_INTENT_REVIEW_TIMEOUT_S", "7")
    assert IntentReviewService(_SlowLLM())._timeout == 7.0
