"""D8 — verifying a command must not run it again.

`StateVerifier.verify_command_execution` took an agent's *claim* that it had
run a command, and for anything it judged critical it re-ran that command and
compared return codes. Measured on the code these tests replace:

    marker exists before verification: True
    marker exists AFTER verification:  False
    verification status: CONTRADICTED

Given a claim about `rm -f <marker>`, the verifier deleted `<marker>`, then
reported the claim CONTRADICTED because the second run's return code differed
from the first. Re-execution does not observe the earlier run; it performs a
second one, and for a mutating command that second run is the harm.

Three further defects sat in the same branch:

  * classification was substring matching, so `terraform apply` and
    `echo confirm` were "critical" -- "rm" is inside "terraform" and
    "confirm" -- and therefore re-executed;
  * it was the codebase's only `create_subprocess_shell`, so `rm -rf /`
    reached a shell without passing BashGuard, which rates it BLOCKED;
  * when re-execution raised, the handler logged a warning and fell through
    to VERIFIED at confidence 0.9 -- the verifier that could not verify
    reporting success.

`StateVerifier` has no importer anywhere in weebot/, cli/, tests/ or
scripts/, so none of this ran in production. It is fixed because the module
is named for security and a future caller would have inherited all four.
"""

from __future__ import annotations

import pathlib

import pytest

from weebot.core.bash_guard import BashGuard, RiskLevel
from weebot.infrastructure.security.state_verifier import (
    CommandExecutionClaim,
    StateVerifier,
    VerificationStatus,
)


@pytest.fixture
def verifier() -> StateVerifier:
    return StateVerifier()


# --------------------------------------------------------------------------
# The defect: verification with side effects.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifying_a_delete_claim_does_not_delete_the_file(verifier, tmp_path):
    """The exact measurement above, pinned."""
    marker = tmp_path / "marker.txt"
    marker.write_text("i exist", encoding="utf-8")

    claim = CommandExecutionClaim(
        command=f"rm -f {marker}", claimed_returncode=0, claimed_output=""
    )
    await verifier.verify_command_execution(claim)

    assert marker.exists(), "verifying the claim executed the command it was checking"
    assert marker.read_text(encoding="utf-8") == "i exist"


@pytest.mark.asyncio
async def test_a_critical_claim_reports_unverifiable_not_verified(verifier, tmp_path):
    """Not re-executing must not be silently reported as success."""
    claim = CommandExecutionClaim(
        command=f"rm -rf {tmp_path}", claimed_returncode=0, claimed_output=""
    )
    result = await verifier.verify_command_execution(claim)

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.confidence_score == 0.0
    assert result.is_trusted is False
    assert "re-execut" in " ".join(result.discrepancies).lower()


@pytest.mark.asyncio
async def test_a_write_claim_does_not_replay_the_write(verifier, tmp_path):
    """A non-idempotent command is the case re-execution corrupts."""
    target = tmp_path / "counter.txt"
    target.write_text("1", encoding="utf-8")
    claim = CommandExecutionClaim(
        command=f"echo 2 > {target} && chmod 600 {target}",
        claimed_returncode=0,
        claimed_output="",
    )
    await verifier.verify_command_execution(claim)
    assert target.read_text(encoding="utf-8") == "1"


# --------------------------------------------------------------------------
# Classification: word boundaries, not substrings.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["terraform apply", "echo confirm", "ls -la", "cat notes.txt"])
def test_an_innocuous_command_is_not_critical(verifier, command):
    assert verifier._is_critical_command(command) is False


@pytest.mark.parametrize("command", ["rm -rf /", "git rm old.py", "chmod 777 /etc", "kill 123"])
def test_a_genuinely_critical_command_is_still_critical(verifier, command):
    assert verifier._is_critical_command(command) is True


# --------------------------------------------------------------------------
# The guard invariant.
# --------------------------------------------------------------------------


def test_the_module_no_longer_reaches_a_shell():
    """CLAUDE.md rule 3. The gate in test_architecture_fitness.py enforces this
    repo-wide; this pins the specific module the violation lived in."""
    source = pathlib.Path(
        "weebot/infrastructure/security/state_verifier.py"
    ).read_text(encoding="utf-8")
    assert "create_subprocess_shell" not in source
    assert "shell=True" not in source


def test_bash_guard_would_have_blocked_the_command_this_module_ran():
    """Context for why the missing guard mattered, not a claim about the fix."""
    assert BashGuard().evaluate("rm -rf /")[0] is RiskLevel.BLOCKED
