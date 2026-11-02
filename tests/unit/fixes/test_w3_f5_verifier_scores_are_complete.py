"""F5: a verifier reply with a missing or malformed axis must not count as a pass.

`_score_output` filled a missing axis with VERIFICATION_SCORE_MIN (3) and the
fail test is `< 3`, so `{}` or `{"correctness": 5}` passed all four checks. A
reply is now parsed into `VerifierScores`; anything that does not parse means the
scorer did not run (NOT_RUN).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.flows.states.verifying import VerifyingState
from weebot.domain.models.audit import VerificationStatus

FULL = '{"correctness": 5, "completeness": 4, "specificity": 3, "restraint": 5}'


def _flow(reply: str) -> MagicMock:
    flow = MagicMock()
    flow._verifier_llm = None
    flow._llm = MagicMock()
    flow._llm.chat = AsyncMock(return_value=SimpleNamespace(content=reply))
    return flow


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        "",
        "{}",
        '{"correctness": 5}',
        '{"correctness": 5, "completeness": 5, "specificity": 5}',
        '{"correctness": "5", "completeness": 5, "specificity": 5, "restraint": 5}',
        '{"correctness": 9, "completeness": 5, "specificity": 5, "restraint": 5}',
        '{"correctness": 0, "completeness": 5, "specificity": 5, "restraint": 5}',
        '{"correctness": true, "completeness": 5, "specificity": 5, "restraint": 5}',
        '{"correctness": 4.5, "completeness": 5, "specificity": 5, "restraint": 5}',
        "not json",
        "[1, 2, 3, 4]",
    ],
)
async def test_an_incomplete_or_invalid_reply_means_the_scorer_did_not_run(reply):
    scores, ran = await VerifyingState()._score_output(_flow(reply), "summary")
    assert ran is False, f"{reply!r} was taken as a real score: {scores}"


@pytest.mark.asyncio
async def test_a_missing_axis_is_not_a_pass():
    _, _, status = await VerifyingState()._score_and_revise(_flow('{"correctness": 5}'), "s")
    assert status is VerificationStatus.NOT_RUN


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [FULL, f"```json\n{FULL}\n```", f"Scores:\n{FULL}"])
async def test_a_full_reply_scores_however_it_is_wrapped(reply):
    scores, ran = await VerifyingState()._score_output(_flow(reply), "summary")
    assert ran is True
    assert scores == {"correctness": 5, "completeness": 4, "specificity": 3, "restraint": 5}


@pytest.mark.asyncio
async def test_a_full_passing_reply_is_passed():
    _, _, status = await VerifyingState()._score_and_revise(_flow(FULL), "s")
    assert status is VerificationStatus.PASSED
