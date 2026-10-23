"""A refused inline script tells the agent the route that is allowed.

Seen in the 2026-10-23 agent-uses batch under enforce: the agent ran
`python -c "..."` through bash, BashGuard rated it "Inline script execution"
(ASK), there was no TTY to approve, and the agent spent minutes trying other
shapes (one task: 145 s). python_execute and running a script file pass the
chain, so the refusal now names them.
"""

from __future__ import annotations

from weebot.application.ports.approval_port import ToolCallApproval
from weebot.application.services.tool_approval import denied_result


def _request(reason: str) -> ToolCallApproval:
    return ToolCallApproval(
        session_id="s",
        tool_name="bash",
        arguments={"command": 'python -c "print(1)"'},
        fingerprint="f",
        guard="bash_guard",
        reason=reason,
    )


def test_an_inline_script_refusal_names_python_execute():
    error = denied_result(_request("dangerous: Inline script execution")).error
    assert "python_execute" in error


def test_other_refusals_are_unchanged():
    error = denied_result(_request("dangerous: Disk format")).error
    assert "python_execute" not in error
