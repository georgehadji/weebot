"""Tests for M7 approval policy hardening."""

import pytest
from weebot.core.approval_policy import ExecApprovalPolicy


class TestApprovalPolicyHardening:
    """M7 — destructive Windows commands require confirmation."""

    @pytest.fixture
    def policy(self):
        return ExecApprovalPolicy()

    def test_reg_delete_always_ask(self, policy):
        result = policy.evaluate("reg delete HKCU\\Software\\X")
        assert result.requires_confirmation is True

    def test_net_user_always_ask(self, policy):
        result = policy.evaluate("net user admin /add")
        assert result.requires_confirmation is True

    def test_icacls_always_ask(self, policy):
        result = policy.evaluate("icacls file.txt /grant everyone:F")
        assert result.requires_confirmation is True

    def test_bcdedit_always_ask(self, policy):
        result = policy.evaluate("bcdedit /set safeboot minimal")
        assert result.requires_confirmation is True

    def test_diskpart_always_ask(self, policy):
        result = policy.evaluate("diskpart /s script.txt")
        assert result.requires_confirmation is True

    def test_schtasks_always_ask(self, policy):
        result = policy.evaluate("schtasks /create /tn test /tr cmd.exe")
        assert result.requires_confirmation is True

    def test_set_content_env_always_ask(self, policy):
        result = policy.evaluate("Set-Content -Path x -Value $env:FOO")
        assert result.requires_confirmation is True

    def test_outfile_absolute_always_ask(self, policy):
        result = policy.evaluate("out-file C:\\Windows\\x.txt")
        assert result.requires_confirmation is True

    def test_chained_output_bypass_blocked(self, policy):
        result = policy.evaluate("remove-item C:\\Output\\x; remove-item C:\\Windows\\x")
        assert result.requires_confirmation is True

    def test_safe_format_table_auto_approved(self, policy):
        result = policy.evaluate("Get-ChildItem | Format-Table")
        assert result.requires_confirmation is False

    def test_safe_get_childitem_auto_approved(self, policy):
        result = policy.evaluate("Get-ChildItem C:\\")
        assert result.requires_confirmation is False
