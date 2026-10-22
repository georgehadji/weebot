"""F07: approval primitives in weebot/core/approval.py.

W1.2: `auto_approve_callback` / `auto_deny_callback` were sync but awaited,
so "auto-approve" denied; `format_prompt` had two lines without the f prefix.
W3.4 (ADR-013): `ApprovalManager` is now the grant store, so the rest of F07
(approval by raw command string, whole-session approval, and BLOCKED being
approvable with `auto_deny_blocked=False`) is gone with the old API; the
grant store is tested in tests/unit/application/services/test_tool_approval.py.
"""

import pytest

from weebot.core.approval import (
    ApprovalDecision,
    ApprovalRequest,
    auto_approve_callback,
    auto_deny_callback,
)
from weebot.core.bash_guard import RiskLevel


@pytest.mark.parametrize(
    ("callback", "expected"),
    [
        (auto_approve_callback, ApprovalDecision.APPROVED),
        (auto_deny_callback, ApprovalDecision.DENIED),
    ],
)
async def test_auto_callbacks_return_their_decision(callback, expected):
    request = ApprovalRequest(command="rm -rf build/", risk_level=RiskLevel.DANGEROUS)
    assert await callback(request) == expected


def test_format_prompt_has_no_unformatted_placeholders():
    prompt = ApprovalRequest(command="ls", risk_level=RiskLevel.SUSPICIOUS).format_prompt()
    assert "{'':" not in prompt
