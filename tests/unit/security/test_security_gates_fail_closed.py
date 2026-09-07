"""Phase 0 / D13–D16 — the fail-open policy, decided at last.

The governing question, open since W2 and escalated rather than answered:

    If a gate's own machinery fails, does it report a violation or report clean?

The answer taken is **split by kind**: security gates fail CLOSED, quality gates
fail open with a loud, distinguishable marker. This file covers the security
half. Each test names the measured fail-open it replaces.

The survey that found these asked the question of every gate module, including
the ten W2 named and never investigated. Four of the findings are live and
blocking; the rest are in modules with no production callers and are recorded
rather than fixed, because a dead gate cannot be a critical defect.
"""

from __future__ import annotations

import base64

import pytest

from weebot.core.approval_policy import (
    ApprovalMode,
    CommandRule,
    ExecApprovalPolicy,
    TOOL_CATEGORIES,
)
from weebot.core.bash_guard import BashGuard, RiskLevel


# ── The egress guard that ungated a whole session ─────────────────────


def test_a_guard_that_cannot_be_built_does_not_latch():
    """`_egress_guard_resolved = True` was set BEFORE the try.

    So if both the DI lookup and the direct construction failed, every later
    call returned the cached None from the early return — and the call site's
    `if guard is not None:` skipped classification for the rest of the session.
    The log said it outright: "outbound tool calls will NOT be gated".
    """
    from weebot.application.agents.executor import _tool_executor as mod

    src = mod.__file__
    with open(src, encoding="utf-8") as fh:
        text = fh.read()

    resolve = text.split("def _get_egress_guard")[1].split("@staticmethod")[0]
    latch = resolve.index("self._egress_guard_resolved = True")
    failure_return = resolve.index("self._egress_guard = None")
    assert latch > failure_return, (
        "the resolved-latch must come AFTER the failure path, so a failure retries"
    )


def test_the_conservative_egress_set_covers_the_outbound_families():
    """With no guard there is no way to inspect a bash command or a browser
    action, so the whole family is refused. Deliberately broader than
    `EgressGuard._detect_egress`, which is the point: this runs only when the
    real classifier could not be built."""
    from weebot.application.agents.executor._tool_executor import ToolExecutor

    for outbound in ("atomic_mail", "bash", "advanced_browser", "telegram_send"):
        assert ToolExecutor._could_be_egress(outbound), outbound
    for local in ("file_editor", "python_execute", "web_search"):
        assert not ToolExecutor._could_be_egress(local), (
            f"{local} is not outbound; refusing it would brick the agent on a "
            "guard outage rather than protect anything"
        )


# ── The approval policy that auto-approved on a typo ──────────────────


def test_an_uncompilable_rule_makes_the_policy_ask_rather_than_approve():
    """The rules include DENY entries, and a bad regex silently dropped one.

    The comment described this as "fail-open: the bad rule is ignored, all
    other rules still apply" — accurate, and the consequence is that a typo in
    a denial becomes an auto-approval with nothing downstream able to tell.
    We cannot know what a rule that will not compile was meant to catch.
    """
    policy = ExecApprovalPolicy(
        rules=[CommandRule(pattern="[unclosed", mode=ApprovalMode.DENY, is_regex=True)]
    )
    result = policy.evaluate("ls -la")
    assert result.requires_confirmation, "a broken rule set must ask, not approve"
    assert not result.approved
    assert "failed to compile" in (result.reason or "")


def test_a_healthy_policy_is_unchanged():
    """REGRESSION GUARD: the fail-closed branch must not swallow the normal path."""
    result = ExecApprovalPolicy().evaluate("ls -la")
    assert result.approved
    assert not result.requires_confirmation


def test_the_categories_the_gates_depend_on_are_present():
    """`get_category_approval_mode` defaults to AUTO_APPROVE on a miss.

    That default is not itself wrong — most categories genuinely are ordinary.
    What is load-bearing is that `inbound_mail` is IN the table: the ADR-006
    inbound-mail gate in `executing.py` rests entirely on this lookup, and if
    the key were renamed or removed the gate would silently stop firing with no
    other symptom. Pinned here so it cannot vanish quietly.
    """
    for category in ("inbound_mail", "finance", "payment"):
        assert category in TOOL_CATEGORIES, f"{category} is gone — a gate just went silent"
        assert TOOL_CATEGORIES[category] == ApprovalMode.FORCE_ALWAYS_ASK


# ── The bash guard that dropped its own blocking rules ────────────────


def test_a_guard_missing_a_blocking_rule_certifies_nothing():
    """A malformed pattern removed the rule it encoded, including BLOCKED ones.

    An earlier pass made that visible in the log and kept skipping, reasoning
    that raising would make the guard unconstructable. The reasoning was sound
    and the outcome was still fail-open: the log went to a file and the command
    ran. Construction still succeeds; what changes is that the guard no longer
    claims anything is safe while a blocking rule is missing.
    """
    broken = BashGuard(custom_patterns=[("[unclosed", RiskLevel.BLOCKED, "d", "s")])
    risk, checks = broken.evaluate("ls -la")
    assert risk == RiskLevel.BLOCKED
    assert checks and "failed to compile" in checks[0].description


def test_a_healthy_bash_guard_is_unchanged():
    """REGRESSION GUARD, and the reason the built-ins matter."""
    guard = BashGuard()
    assert guard.evaluate("ls -la")[0] == RiskLevel.SAFE
    assert guard.evaluate("rm -rf /")[0] == RiskLevel.BLOCKED


def test_every_builtin_pattern_compiles():
    """The fix above only stays inert because this holds.

    If a built-in ever failed to compile, `evaluate` would refuse every command
    — correct, and catastrophic. This makes that a test failure instead.
    """
    assert BashGuard()._dropped_blocking == []


# ── The obfuscation check that reported clean on what it could not read ──


def test_an_undecodable_blob_is_refused_rather_than_waved_through():
    """Both decode failures fell through to `return True, ""`.

    A 100+ character base64-looking blob that neither decoder could read was
    reported CLEAN — the one outcome an obfuscation check must never produce,
    because the payload it cannot read is exactly the one worth refusing.
    """
    from weebot.tools.bash_tool import BashTool

    tool = BashTool()
    # 101 characters: valid base64 alphabet, invalid length for either decoder.
    allowed, message = tool._legacy_validate_no_encoded_commands("echo " + "A" * 101)
    assert not allowed
    assert "could not decode" in message


@pytest.mark.parametrize(
    "label, command",
    [
        ("plain", "ls -la /tmp"),
        ("harmless long base64", "echo " + base64.b64encode(b"x" * 120).decode()),
    ],
)
def test_ordinary_commands_still_pass_the_obfuscation_check(label, command):
    """REGRESSION GUARD: refusing what cannot be decoded must not refuse what can."""
    from weebot.tools.bash_tool import BashTool

    allowed, _ = BashTool()._legacy_validate_no_encoded_commands(command)
    assert allowed, label


def test_an_encoded_shell_command_is_still_caught():
    """REGRESSION GUARD for the detection the check exists for."""
    from weebot.tools.bash_tool import BashTool

    payload = base64.b64encode(b"rm -rf / " + b"pad" * 50).decode()
    allowed, message = BashTool()._legacy_validate_no_encoded_commands("echo " + payload)
    assert not allowed
    assert "Suspicious encoded shell command" in message
