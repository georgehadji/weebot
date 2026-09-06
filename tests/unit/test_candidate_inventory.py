"""The candidate inventory must agree with the audits, in both directions.

Phase B1 of tasks/specs/review_gate_and_residual_work_plan.md.

The 25 uninvestigated candidates were recorded as Markdown tables spread across
nine audit files. Readable, but not checkable: nothing counted them, nothing
prevented one being quietly dropped, and answering *"what is still open?"* meant
re-reading nine documents — which is what happened when the question was last
asked, and it is how D1, D2 and D7 came to exist as numbers with no claims
attached that nobody noticed for nine waves.

`tasks/audits/candidates.yml` is now the source of truth. These tests keep it
honest:

1. **Every id the audits mention exists in the inventory** — a candidate cannot
   be dropped by being deleted from a table.
2. **Every `cleared` or `deferred` record carries a `verdict_note`** — the
   protocol's Phase 4 rule, that a candidate may not be dismissed silently,
   expressed as a test rather than as a convention.
3. **Every `fixed` record names an `evidence` file that exists** — a fix claim
   is only as good as the proof test it points at, and a renamed test file
   would otherwise leave the claim standing with nothing behind it.

Direction (1) is the one that matters most: without it the inventory could drift
into an optimistic subset of reality, which is the failure this whole exercise
exists to prevent.
"""

from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_INVENTORY = _ROOT / "tasks" / "audits" / "candidates.yml"
_AUDITS = _ROOT / "tasks" / "audits"

# Candidate ids look like D30 or S4. Two digits at most, so that bandit codes
# (B110) and ruff codes (S110, E501) cannot be mistaken for candidates -- `S110`
# appears in the baseline audit as a *rule* name, not a candidate.
#
# The trailing lookahead drops the opening half of a range: the baseline writes
# "Entry material is §7.3 D1-D12", which points at a plan section and is not a
# claim about D1. The closing half still matches, which is correct -- D12 is a
# real candidate with its own record.
_ID = re.compile(r"\b([DS])([0-9]{1,2})\b(?![–—-][DS][0-9])")

# Audit files that predate the defect hunt and use D/S numbering for other
# things, or that are narrative rather than triage.
#
# `residual_b1_inventory.md` is excluded for a different reason worth stating:
# it is the document *about* this inventory, so it necessarily names the
# numbering gaps in order to explain that they have no claim. Scanning it makes
# the gap guard below fail on its own documentation -- which it did, on the
# first full run. Candidate claims are not written there, so the exclusion
# costs nothing.
_NOT_HUNT_AUDITS = (
    "weebot_architecture_audit",
    "phase",
    "cross_phase",
    "weebot_refactoring",
    "residual_b1_inventory",
)

_VALID_STATUSES = frozenset({"open", "investigating", "confirmed", "fixed", "cleared", "deferred"})
_NEEDS_NOTE = frozenset({"cleared", "deferred"})


def _inventory() -> dict:
    return yaml.safe_load(_INVENTORY.read_text(encoding="utf-8"))


def _records() -> list[dict]:
    return _inventory()["candidates"]


def _hunt_audit_files() -> list[pathlib.Path]:
    return [
        p
        for p in sorted(_AUDITS.glob("*.md"))
        if not any(p.name.startswith(prefix) for prefix in _NOT_HUNT_AUDITS)
    ]


def _ids_mentioned_in_audits() -> dict[str, list[str]]:
    """Map candidate id -> the audit files mentioning it."""
    found: dict[str, list[str]] = {}
    for path in _hunt_audit_files():
        for letter, number in _ID.findall(path.read_text(encoding="utf-8")):
            found.setdefault(f"{letter}{number}", []).append(path.name)
    return found


class TestTheInventoryIsWellFormed:
    def test_it_parses_and_is_not_empty(self):
        records = _records()
        assert len(records) >= 40, f"only {len(records)} candidates; the audits describe far more"

    def test_ids_are_unique(self):
        ids = [r["id"] for r in _records()]
        duplicates = {i for i in ids if ids.count(i) > 1}
        assert duplicates == set(), f"duplicate ids: {sorted(duplicates)}"

    def test_every_record_has_the_required_fields(self):
        missing = [
            f"{r.get('id', '<no id>')}: {field}"
            for r in _records()
            for field in ("id", "wave", "location", "claim", "status")
            if not r.get(field)
        ]
        assert missing == [], f"records missing required fields: {missing}"

    def test_statuses_are_from_the_declared_vocabulary(self):
        bad = [(r["id"], r["status"]) for r in _records() if r["status"] not in _VALID_STATUSES]
        assert bad == [], f"unknown status values: {bad}; valid are {sorted(_VALID_STATUSES)}"


class TestNothingCanBeDroppedSilently:
    """Direction (1): the audits are checked against the inventory, not trusted."""

    def test_every_id_in_the_audits_is_in_the_inventory(self):
        known = {r["id"] for r in _records()}
        gaps = set(_inventory()["meta"]["numbering_gaps"])
        missing = {
            candidate_id: sorted(set(files))
            for candidate_id, files in _ids_mentioned_in_audits().items()
            if candidate_id not in known and candidate_id not in gaps
        }
        assert missing == {}, (
            "these candidate ids appear in the audits but not in candidates.yml. "
            "Add a record, or add the id to meta.numbering_gaps with a reason.\n"
            + "\n".join(f"  {k}: {v}" for k, v in sorted(missing.items()))
        )

    def test_the_recorded_numbering_gaps_really_have_no_claim(self):
        """Guard the escape hatch: a gap must actually be absent from the audits.

        Otherwise `meta.numbering_gaps` becomes a way to hide a real candidate
        from the check above.
        """
        mentioned = _ids_mentioned_in_audits()
        for gap in _inventory()["meta"]["numbering_gaps"]:
            files = [f for f in mentioned.get(gap, []) if f != "candidates.yml"]
            assert not files, (
                f"{gap} is listed as a numbering gap but is mentioned in {sorted(set(files))}. "
                "If it has a claim, it needs a record."
            )


class TestNoCandidateIsDismissedSilently:
    """Direction (2): the protocol's Phase 4 rule, as a test."""

    def test_cleared_and_deferred_records_carry_a_verdict_note(self):
        silent = [
            r["id"]
            for r in _records()
            if r["status"] in _NEEDS_NOTE and not (r.get("verdict_note") or "").strip()
        ]
        assert silent == [], (
            "these candidates were dismissed without a recorded reason: "
            f"{silent}. A `cleared` or `deferred` verdict needs a verdict_note."
        )

    def test_open_records_have_no_verdict_note(self):
        """An `open` candidate has not been judged, so it cannot carry a verdict."""
        contradictory = [
            r["id"] for r in _records() if r["status"] == "open" and (r.get("verdict_note") or "")
        ]
        assert contradictory == [], (
            f"these are marked open but carry a verdict_note: {contradictory}. "
            "Either they were investigated (change the status) or the note is stale."
        )


class TestFixClaimsPointAtRealProof:
    """Direction (3): a fix claim is only as good as the test behind it."""

    def test_every_fixed_record_names_an_evidence_file(self):
        unproven = [r["id"] for r in _records() if r["status"] == "fixed" and not r.get("evidence")]
        assert unproven == [], f"marked fixed with no evidence path: {unproven}"

    def test_every_evidence_path_exists(self):
        """Evidence is `path` or the more precise `path::test_name`.

        A bare path only promises the file exists; a nodeid names the single
        test that proves the claim, and is checked to that depth -- the
        function must be defined in the file. Accepting the nodeid without
        verifying it would be worse than not allowing it, because a typo would
        read as stronger evidence than a plain path while proving less.
        """
        missing = []
        for r in _records():
            evidence = r.get("evidence")
            if not evidence:
                continue
            path, _, nodeid = evidence.partition("::")
            target = _ROOT / path
            if not target.is_file():
                missing.append(f"{r['id']} -> {evidence} (no such file)")
                continue
            if nodeid:
                name = nodeid.rpartition("::")[2]
                source = target.read_text(encoding="utf-8")
                if f"def {name}(" not in source:
                    missing.append(f"{r['id']} -> {evidence} (no such test in the file)")
        assert missing == [], (
            "evidence named by the inventory does not exist. A renamed or "
            f"deleted proof test leaves a fix claim with nothing behind it:\n  {missing}"
        )


def test_report_the_open_count(capsys):
    """Not an assertion — the number the plan wanted a build to print."""
    records = _records()
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    with capsys.disabled():
        print(f"\n  candidate inventory: {len(records)} records")
        for status in sorted(counts):
            print(f"    {status:13} {counts[status]:3}")
        outstanding = counts.get("open", 0) + counts.get("deferred", 0)
        print(f"    {'-> not closed':13} {outstanding:3}")
