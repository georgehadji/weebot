"""BashGuard reads recursive deletes by token, so extra flags cannot hide a root or home delete."""

import pytest

from weebot.core.bash_guard import BashGuard, RiskLevel


@pytest.mark.parametrize("command", ["rm -rfv /", "rm -rvf /", "rm -r -v /"])
def test_root_delete_with_extra_flags_is_blocked(command):
    assert BashGuard().evaluate(command)[0] == RiskLevel.BLOCKED


@pytest.mark.parametrize("command", ["rm -rf ~", "rm -rfv ~", "rm -rf $HOME"])
def test_home_delete_is_not_safe(command):
    assert BashGuard().evaluate(command)[0] in (RiskLevel.DANGEROUS, RiskLevel.BLOCKED)


def test_plain_command_stays_safe():
    assert BashGuard().evaluate("echo hello")[0] == RiskLevel.SAFE
