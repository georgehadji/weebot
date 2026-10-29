"""R15 (audit 2026-10-29): the approval prompt shows the call the human is approving.

It showed ``command[:500]`` and nothing for other tools, while the approval covered the
whole call: a command whose first 500 characters were harmless hid its tail, and an
image_gen or video_gen call (paid) was approved with no arguments shown at all.
"""

from __future__ import annotations

from weebot.application.ports.approval_port import ToolCallApproval
from weebot.application.services.tool_approval import approval_prompt


def _request(tool: str, **arguments) -> ToolCallApproval:
    return ToolCallApproval(
        session_id="s", tool_name=tool, arguments=arguments, fingerprint="f",
        guard="exec_approval_policy", reason="confirm",
    )


def test_the_tail_of_a_long_command_is_shown():
    command = "Get-ChildItem Output | Out-Null; " * 18 + r"Remove-Item -Recurse C:\Users\x"
    assert len(command) > 500
    for short in (False, True):
        assert r"Remove-Item -Recurse C:\Users\x" in approval_prompt(
            _request("powershell", command=command), short=short
        )


def test_a_huge_value_says_how_much_is_hidden_and_keeps_both_ends():
    command = "echo start " + "x" * 20_000 + " rm -rf ~/important"
    prompt = approval_prompt(_request("bash", command=command))
    assert "echo start" in prompt and "rm -rf ~/important" in prompt
    assert "characters hidden" in prompt
    assert len(prompt) < 6_000


def test_other_tools_show_their_arguments():
    prompt = approval_prompt(
        _request("image_gen", prompt="a red fox", output_path="Output/fox.png", model="m")
    )
    assert "a red fox" in prompt and "Output/fox.png" in prompt


def test_secrets_in_arguments_are_redacted():
    prompt = approval_prompt(
        _request("bash", command="curl -H 'Authorization: Bearer ghp_0123456789abcdefABCD'")
    )
    assert "ghp_0123456789abcdefABCD" not in prompt
