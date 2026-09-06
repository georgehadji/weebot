"""Debt ceilings must be able to move in exactly one direction.

Phase B2 of tasks/specs/review_gate_and_residual_work_plan.md.

Five ceilings lived in three places — two as `CEILING` constants in Python
scripts, two as `?=` variables in the Makefile, one added later — and the
arrangement had three defects:

1. **Nothing enforced "never raise it."** The rule was a comment.
2. **Nothing rewarded lowering it.** One script printed *"Ceiling can be lowered
   to N"* as advice, which would be ignored indefinitely, and the slack between
   actual and ceiling is where a regression hides until it reaches the top.
3. **Two could be disarmed from the environment.** `?=` takes an override from
   the command line or environment, so `PRINT_CEILING=99999 make lint-no-print`
   passed with 143 findings — and CI runs those targets.

The rule is now exact equality in both directions, applied from one place, over
data that no environment variable can reach.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CEILINGS = _ROOT / "tasks" / "quality" / "ceilings.toml"
_MAKEFILE = _ROOT / "Makefile"

_EXPECTED = {
    "silent_except_handlers",
    "blocking_io_in_async",
    "print_in_production",
    "bare_env_reads",
    "bandit_b110",
    # ruff F841 — locals assigned and never read. Added after the same defect
    # was found twice in one session (an MCP server process bound to a local
    # nothing could reach, and a steering prompt built, logged, and not sent),
    # both of which ruff had been reporting while CI's selector never asked.
    "unused_locals",
}


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "quality_ceilings", _ROOT / "scripts" / "quality_ceilings.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qc = _load_module()


class TestTheCeilingsFile:
    def test_it_holds_every_ratchet(self):
        assert set(qc.load()) == _EXPECTED

    def test_every_ceiling_is_a_non_negative_int(self):
        bad = {k: v for k, v in qc.load().items() if not isinstance(v, int) or v < 0}
        assert bad == {}, f"ceilings must be non-negative integers: {bad}"

    def test_no_ceiling_constant_survives_in_the_scripts(self):
        """One source of truth means the old constants must be gone, not shadowed."""
        offenders = [
            p.name
            for p in sorted((_ROOT / "scripts").glob("lint_*.py"))
            if "CEILING = " in p.read_text(encoding="utf-8")
        ]
        assert offenders == [], (
            f"these still define their own ceiling: {offenders}. "
            "A second source of truth is how the two drift apart."
        )


class TestTheRuleIsBidirectional:
    """The half that is new: falling below the ceiling must also fail."""

    @pytest.fixture
    def table(self) -> dict[str, int]:
        return {"demo": 10}

    def test_at_the_ceiling_passes(self, table):
        code, msg = qc.check("demo", 10, table)
        assert code == 0
        assert "at its ceiling" in msg

    def test_above_the_ceiling_fails(self, table):
        code, msg = qc.check("demo", 11, table)
        assert code == 1
        assert "exceeds" in msg

    def test_below_the_ceiling_fails_and_says_what_to_write(self, table):
        """The whole design. A cleanup that is not locked in becomes slack."""
        code, msg = qc.check("demo", 7, table)
        assert code == 1
        assert "BELOW" in msg
        assert "demo = 7" in msg, "the message must name the value to write"

    def test_zero_is_a_legitimate_ceiling(self):
        assert qc.check("demo", 0, {"demo": 0})[0] == 0
        assert qc.check("demo", 1, {"demo": 0})[0] == 1

    def test_an_unknown_ceiling_is_an_error_not_a_pass(self, table):
        """A typo'd name must not silently gate nothing."""
        code, msg = qc.check("nope", 0, table)
        assert code == 1
        assert "unknown ceiling" in msg


class TestTheUpwardGuard:
    """`actual == ceiling` cannot see a ceiling raised alongside its debt."""

    def _run(self, tmp_path, before: str, after: str) -> tuple[int, str]:
        """Build a throwaway repo with two commits and compare them."""
        repo = tmp_path / "repo"
        (repo / "tasks" / "quality").mkdir(parents=True)
        (repo / "scripts").mkdir()
        target = repo / "tasks" / "quality" / "ceilings.toml"
        script = repo / "scripts" / "quality_ceilings.py"
        script.write_text(
            (_ROOT / "scripts" / "quality_ceilings.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        def git(*args):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        target.write_text(before, encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "before")
        # Tag the baseline rather than branching to it. `git branch -M base`
        # renames the *current* branch, so the next commit moves `base` too and
        # every comparison is against itself -- which passes for the wrong
        # reason. A tag stays put.
        git("tag", "base")
        target.write_text(after, encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "after", "--allow-empty")

        proc = subprocess.run(
            ["python", "scripts/quality_ceilings.py", "--verify-not-raised", "--baseline", "base"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def test_a_raised_ceiling_is_rejected(self, tmp_path):
        code, out = self._run(
            tmp_path, "[ceilings]\ndemo = 10\n", "[ceilings]\ndemo = 11\n"
        )
        assert code == 1
        assert "RAISED" in out
        assert "10 -> 11" in out

    def test_a_lowered_ceiling_is_accepted(self, tmp_path):
        code, out = self._run(tmp_path, "[ceilings]\ndemo = 10\n", "[ceilings]\ndemo = 4\n")
        assert code == 0
        assert "10 -> 4" in out

    def test_an_unchanged_ceiling_is_accepted(self, tmp_path):
        code, _ = self._run(tmp_path, "[ceilings]\ndemo = 10\n", "[ceilings]\ndemo = 10\n")
        assert code == 0

    def test_a_new_ceiling_is_accepted(self, tmp_path):
        code, out = self._run(
            tmp_path, "[ceilings]\ndemo = 10\n", "[ceilings]\ndemo = 10\nextra = 3\n"
        )
        assert code == 0
        assert "extra" in out

    def test_an_unresolvable_baseline_fails_rather_than_passes(self):
        """An unfetched base branch is not approval.

        This is the fail-open trap the whole programme exists to remove, in the
        guard itself: git returns the same exit code for "the file is new" and
        "I could not look", and collapsing them would make a missing fetch read
        as a green light.
        """
        code, msg = qc.verify_not_raised("refs/heads/definitely-not-a-real-ref")
        assert code == 1
        assert "CANNOT VERIFY" in msg


class TestTheEnvironmentCannotDisarmThem:
    """Defect 3: `?=` took an override from the command line or environment."""

    def test_the_makefile_defines_no_ceiling_variables(self):
        text = _MAKEFILE.read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in text.splitlines()
            if "CEILING" in line and "?=" in line
        ]
        assert offenders == [], (
            "a `?=` ceiling in the Makefile can be overridden from the environment, "
            f"which disarms the ratchet: {offenders}"
        )

    def test_the_ratchet_targets_go_through_the_shared_checker(self):
        text = _MAKEFILE.read_text(encoding="utf-8")
        for name in ("print_in_production", "bare_env_reads"):
            assert f"--check {name}" in text, f"{name} is not checked via quality_ceilings.py"
