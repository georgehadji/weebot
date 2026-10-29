"""R01 (audit 2026-10-29): a newline separates shell commands, so it separates segments.

PowerShell and bash run each line as its own command, but the policy split only on
``; && || | &``. A destructive command on the line after an auto-approved Output\\ write
was judged as part of that write and ran unasked; a command after ``ls`` on a new line
counted as a plain read. Python passed by python_execute stays one block.

The Output\\ carve-out also judged paths against the process cwd while the command ran in
``working_dir``, so ``Remove-Item Output\\data.csv`` in another project was auto-approved.
"""

from __future__ import annotations

import pytest

from weebot.application.services.tool_guards import ApprovalPolicyAdapter, GuardAction
from weebot.core.approval_policy import (
    ExecApprovalPolicy,
    SegmentSyntax,
    is_read_only_segment,
    split_segments,
)

DELETE = r"Remove-Item -Force -Recurse C:\Users\someone\Documents\X"


@pytest.mark.parametrize("sep", ["\n", "\r\n", "\r"])
def test_a_delete_after_an_output_write_still_asks(sep):
    result = ExecApprovalPolicy().evaluate("Set-Content Output\\a.txt hi" + sep + DELETE)
    assert result.requires_confirmation, "the newline hid the delete from the policy"


@pytest.mark.parametrize("sep", ["\n", "\r\n", "\r"])
def test_a_command_after_a_read_on_a_new_line_is_not_a_read(sep):
    unreviewed = ExecApprovalPolicy().unreviewed_segments("ls" + sep + r"ri -r -fo C:\x")
    assert unreviewed == [r"ri -r -fo C:\x"]


def test_env_with_a_command_is_not_a_plain_read():
    assert is_read_only_segment("env") is True
    assert is_read_only_segment("env rm -rf X") is False


def test_shell_splits_on_newlines_and_python_does_not():
    assert split_segments("a\nb\r\nc") == ["a", "b", "c"]
    assert split_segments("x = 1\ny = 2", syntax=SegmentSyntax.PYTHON) == ["x = 1\ny = 2"]


def test_a_newline_inside_quotes_stays_in_its_segment():
    command = "Set-Content Output\\a.txt 'line one\nline two'"
    assert split_segments(command) == [command]
    assert not ExecApprovalPolicy().evaluate(command).requires_confirmation


def test_a_plain_output_write_is_still_auto_approved():
    assert not ExecApprovalPolicy().evaluate("Set-Content Output\\a.txt hi").requires_confirmation


def test_multi_line_python_is_still_one_block():
    adapter = ApprovalPolicyAdapter()
    assert adapter.check("python_execute", {"code": "x = 1\ny = 2\nprint(x + y)"}) is None


def test_the_output_carve_out_follows_the_working_dir(tmp_path):
    other = tmp_path / "other_project"
    other.mkdir()
    command = "Remove-Item Output\\data.csv"
    assert not ExecApprovalPolicy().evaluate(command).requires_confirmation  # this workspace
    assert ExecApprovalPolicy().evaluate(command, cwd=str(other)).requires_confirmation
    verdict = ApprovalPolicyAdapter().check(
        "powershell", {"command": command, "working_dir": str(other)}
    )
    assert verdict is not None and verdict.action is GuardAction.ASK


@pytest.mark.asyncio
async def test_bash_tool_judges_the_command_where_it_will_run(tmp_path):
    from weebot.tools.bash_tool import BashTool

    class _Sandbox:
        calls: list = []

        async def execute_shell(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("the command ran without approval")

    other = tmp_path / "other_project"
    other.mkdir()
    tool = BashTool(sandbox=_Sandbox())
    result = await tool.execute(command="Remove-Item Output\\data.csv", working_dir=str(other))
    assert result.error and "confirmation" in result.error
    assert _Sandbox.calls == []
