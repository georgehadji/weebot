"""Unit tests for ExecApprovalPolicy."""

from weebot.core.approval_policy import ExecApprovalPolicy, ApprovalMode, CommandRule


class TestDefaultPolicy:
    def setup_method(self):
        self.policy = ExecApprovalPolicy()

    def test_non_critical_command_auto_approved(self):
        result = self.policy.evaluate("Get-ChildItem C:\\")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_delete_command_requires_confirmation_by_default(self):
        result = self.policy.evaluate("Remove-Item old_logs")
        assert result.requires_confirmation is True

    def test_format_command_denied_by_default(self):
        result = self.policy.evaluate("Format-Volume C")
        assert result.approved is False

    def test_result_has_undo_hint(self):
        result = self.policy.evaluate("Remove-Item log.txt")
        assert isinstance(result.undo_hint, str)


class TestCustomRules:
    def test_whitelist_rule_auto_approves(self):
        policy = ExecApprovalPolicy(
            rules=[CommandRule(pattern="Get-Process", mode=ApprovalMode.AUTO_APPROVE)]
        )
        result = policy.evaluate("Get-Process chrome")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_deny_rule_blocks_command(self):
        policy = ExecApprovalPolicy(rules=[CommandRule(pattern="curl", mode=ApprovalMode.DENY)])
        result = policy.evaluate("curl http://example.com")
        assert result.approved is False

    def test_ask_rule_requires_confirmation(self):
        policy = ExecApprovalPolicy(
            rules=[CommandRule(pattern="npm install", mode=ApprovalMode.ALWAYS_ASK)]
        )
        result = policy.evaluate("npm install --save-dev")
        assert result.requires_confirmation is True

    def test_most_specific_rule_wins(self):
        policy = ExecApprovalPolicy(
            rules=[
                CommandRule(pattern="Remove-Item", mode=ApprovalMode.ALWAYS_ASK),
                CommandRule(pattern="Remove-Item C:\\Windows", mode=ApprovalMode.DENY),
            ]
        )
        result = policy.evaluate("Remove-Item C:\\Windows\\system32")
        assert result.approved is False


class TestApprovalResult:
    def test_result_contains_command(self):
        policy = ExecApprovalPolicy()
        result = policy.evaluate("Get-ChildItem")
        assert result.command == "Get-ChildItem"


class TestInvalidRegexHandling:
    """Black swan fix: invalid regex in a user-supplied rule must not crash evaluate().

    Before the fix, re.search(bad_pattern, ...) would raise re.error at
    runtime, propagating through BashTool.execute() and killing the agent.

    POLICY CHANGE, Phase 0. These tests used to assert that a broken rule was
    skipped and the command auto-approved. That was the *undecided* behaviour:
    W2 escalated "should a gate that cannot run report clean?" as a product
    question and left the tests pinning the status quo so nobody could answer
    it by accident. The answer is now taken — security gates fail closed — so
    the assertions record the decision instead of the placeholder.

    The rules include DENY entries. Skipping one turned a denial into an
    auto-approval, and nothing downstream could tell.
    """

    def test_invalid_regex_does_not_raise_on_evaluate(self):
        """Still must not raise. It must now ASK rather than auto-approve."""
        policy = ExecApprovalPolicy(
            rules=[CommandRule(pattern="[unclosed", mode=ApprovalMode.DENY, is_regex=True)]
        )
        result = policy.evaluate("any command here")
        assert result.approved is False
        assert result.requires_confirmation is True
        assert "failed to compile" in result.reason

    def test_invalid_regex_does_not_block_valid_literal_rules(self):
        """An invalid regex rule must not prevent valid literal rules from matching.

        NOTE: this now passes for a different reason than it used to. The
        command is still not approved, but because the whole policy refuses
        while a rule is broken — not because the literal rule matched. The
        distinction is recorded rather than hidden; the valid-rule path is
        covered by the healthy-policy tests elsewhere in this file.
        """
        policy = ExecApprovalPolicy(
            rules=[
                CommandRule(pattern="(dangling", mode=ApprovalMode.DENY, is_regex=True),
                CommandRule(pattern="format", mode=ApprovalMode.DENY),
            ]
        )
        result = policy.evaluate("format C:")
        assert result.approved is False

    def test_valid_regex_still_fires_alongside_invalid(self):
        """A valid regex rule must still match correctly when mixed with invalid ones."""
        policy = ExecApprovalPolicy(
            rules=[
                CommandRule(pattern="[bad", mode=ApprovalMode.DENY, is_regex=True),
                CommandRule(pattern=r"rm\s+-rf", mode=ApprovalMode.DENY, is_regex=True),
            ]
        )
        result = policy.evaluate("rm -rf /important")
        assert result.approved is False

    def test_multiple_invalid_regexes_are_reported_not_skipped(self):
        """Multiple invalid patterns must not cause cumulative failures.

        They must also not be quietly ignored: the count reaches the caller so
        the message says how much of the policy is not running.
        """
        policy = ExecApprovalPolicy(
            rules=[
                CommandRule(pattern="[a", mode=ApprovalMode.DENY, is_regex=True),
                CommandRule(pattern="(b", mode=ApprovalMode.DENY, is_regex=True),
                CommandRule(pattern="*c", mode=ApprovalMode.DENY, is_regex=True),
            ]
        )
        result = policy.evaluate("ls -la")
        assert result.requires_confirmation is True
        assert "3 approval rule(s) failed to compile" in result.reason


class TestOutputDirectoryAllowlist:
    """Remove-Item inside Output\\ must be auto-approved; outside must still ask."""

    def setup_method(self):
        self.policy = ExecApprovalPolicy()

    def test_remove_item_in_output_dir_auto_approved(self):
        result = self.policy.evaluate("Remove-Item 'E:\\Output\\marina-kotsi\\temp'")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_remove_item_in_output_dir_case_insensitive(self):
        result = self.policy.evaluate("Remove-Item C:/output/project/node_modules")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_remove_item_outside_output_dir_still_asks(self):
        result = self.policy.evaluate("Remove-Item 'C:\\Windows\\System32\\cmd.exe'")
        assert result.requires_confirmation is True

    def test_remove_item_bare_path_still_asks(self):
        result = self.policy.evaluate("Remove-Item old_logs")
        assert result.requires_confirmation is True
