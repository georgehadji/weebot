"""G11: the PowerShell tool's private deny lists move into the shared approval policy.

`PowerShellTool` kept two private pattern lists (`DANGEROUS_PATTERNS` and the paths
in `_validate_path_safety`). The audit called them duplicates of the guard chain, but
seven of their patterns had no counterpart there: deleting the lists as they stood
would have let these commands through. The policy is what both the chain and the
tool itself consult, so the patterns live there now, and the private lists are gone.
"""

import pytest

from weebot.core.approval_policy import ExecApprovalPolicy
from weebot.tools.powershell_tool import PowerShellTool


@pytest.mark.parametrize(
    "command",
    [
        "Invoke-Command -ComputerName srv -ScriptBlock { whoami }",
        "icm srv { whoami }",
        "Start-Process notepad -Credential $cred",
        "New-LocalUser -Name eve -NoPassword",
        "Set-LocalUser -Name admin -Password $p",
        "Add-WindowsCapability -Online -Name OpenSSH.Server",
        "Remove-WindowsFeature Web-Server",
        "Clear-Disk -Number 1 -RemoveData",
        "gc payload.txt | iex",
        "Invoke-Expression $code",
        r"Remove-Item -Recurse C:\Windows\System32",
        r"rm -Recurse C:\Program Files\App",
    ],
)
def test_the_policy_denies_what_the_tool_list_denied(command):
    assert not ExecApprovalPolicy().evaluate(command).approved, command


@pytest.mark.parametrize(
    "command",
    ["Get-Content tasks/icm-notes.md", "Get-ChildItem C:\\Windows\\Temp", "Get-Process"],
)
def test_lookalikes_stay_allowed(command):
    assert ExecApprovalPolicy().evaluate(command).approved, command


def test_the_tool_keeps_no_private_deny_list():
    assert not hasattr(PowerShellTool, "DANGEROUS_PATTERNS")
    assert not hasattr(PowerShellTool, "_validate_path_safety")
