"""D4: the rules only the dead validators had now live in the shared gates.

`CommandValidator` and `tools/validation.py` had no caller, but measured against the
live guard chain they caught five commands it let through. Wiring the validators
whole would also have refused ordinary commands (any `$(...)`, `re.compile(`), so
only these rules move into the approval policy and BashGuard.
"""

import pytest

from weebot.application.services.tool_guards import GuardAction, default_guard_chain


def _action(tool: str, command: str) -> GuardAction:
    chain = default_guard_chain(include_egress=False)
    return chain.evaluate(tool, {"command": command}).verdict.action


@pytest.mark.parametrize(
    ("tool", "command"),
    [
        ("powershell", "powershell -ExecutionPolicy Bypass -File a.ps1"),
        ("powershell", "pwsh -ep bypass -File a.ps1"),
        ("bash", "powershell.exe -executionpolicy bypass -c whoami"),
        ("powershell", r"cipher /w:C:\ "),
        ("powershell", "cacls secret.txt /grant everyone:f"),
        ("bash", "eval $PAYLOAD"),
        ("bash", 'eval "$CMD"'),
    ],
)
def test_the_moved_rules_stop_the_command(tool, command):
    assert _action(tool, command) >= GuardAction.ASK, command


@pytest.mark.parametrize(
    ("tool", "command"),
    [
        ("bash", "echo $(date +%s)"),
        ("bash", "docker run -v $(pwd):/app img"),
        ("bash", "grep -rn 're.compile(' src"),
        ("powershell", "Get-ExecutionPolicy"),
        ("bash", "echo evaluation done"),
    ],
)
def test_ordinary_commands_still_pass(tool, command):
    assert _action(tool, command) == GuardAction.ALLOW, command
