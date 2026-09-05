#!/usr/bin/env python3
"""Report whether main's live protection still matches `.github/rulesets/main.json`.

Phase A2 of tasks/specs/review_gate_and_residual_work_plan.md. Protection that
only exists in the web UI is protection nobody can review and nobody notices
the loss of. This reads the live ruleset back and compares it to the file.

**The one rule this script exists to obey: it exits 0 only when it has read the
live configuration and found it matching.** Every other outcome -- no token,
403, 404, a network error, a malformed response -- is a failure. A drift
detector that passes when it cannot see is the same fail-open control the whole
V7 programme was spent removing, one layer up. "I could not check" is not
"nothing is wrong".

`[UNK]` Two things this script cannot settle on its own and its first live run
will:

1. **Whether the account's plan permits rulesets on a private repository.**
   georgehadji/weebot is private. Availability of rulesets and of classic
   branch protection differs by plan and has changed over time; if the answer
   is no, this is a billing decision rather than a configuration one, and the
   script will say so rather than guess.
2. **Whether a token is available that can read it.** The Actions
   `GITHUB_TOKEN` cannot be granted repository-administration scope through the
   workflow `permissions:` key, so this most likely needs a PAT in
   `secrets.PROTECTION_READ_TOKEN`. If that is missing the script fails loudly
   instead of skipping, because a skipped verification reads as "fine".

Exit code: 0 only on a verified match; 1 on drift, or on any inability to
verify.

Usage:
    GITHUB_TOKEN=<token> python scripts/check_branch_protection.py
    python scripts/check_branch_protection.py --repo owner/name
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RULESET = _ROOT / ".github" / "rulesets" / "main.json"
_DEFAULT_REPO = "georgehadji/weebot"
_API = "https://api.github.com"

OK = 0
FAIL = 1


def _contexts(ruleset: dict) -> set[str]:
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "required_status_checks":
            params = rule.get("parameters", {})
            return {c.get("context", "") for c in params.get("required_status_checks", [])}
    return set()


def _review_count(ruleset: dict) -> int | None:
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "pull_request":
            return rule.get("parameters", {}).get("required_approving_review_count")
    return None


def compare(intended: dict, live: dict) -> list[str]:
    """Return the differences that matter. Empty means the live state is intact.

    Deliberately not a byte comparison: the API adds `id`, `source`,
    `created_at` and `_links`, none of which are policy. What is compared is
    what an attacker or an accident would have to change to weaken the gate.
    """
    diffs: list[str] = []

    if live.get("enforcement") != intended.get("enforcement"):
        diffs.append(
            f"enforcement is {live.get('enforcement')!r}, expected "
            f"{intended.get('enforcement')!r}"
        )

    intended_types = {r.get("type") for r in intended.get("rules", [])}
    live_types = {r.get("type") for r in live.get("rules", [])}
    for missing in sorted(intended_types - live_types):
        diffs.append(f"rule {missing!r} is no longer present")

    want, got = _contexts(intended), _contexts(live)
    for missing in sorted(want - got):
        diffs.append(f"required check {missing!r} is no longer required")
    for extra in sorted(got - want):
        diffs.append(f"required check {extra!r} is required but not in the file")

    want_reviews, got_reviews = _review_count(intended), _review_count(live)
    if want_reviews is not None and got_reviews != want_reviews:
        diffs.append(
            f"required_approving_review_count is {got_reviews}, expected {want_reviews}"
        )

    if not intended.get("bypass_actors") and live.get("bypass_actors"):
        actors = [a.get("actor_id") for a in live.get("bypass_actors", [])]
        diffs.append(f"bypass actors have been added: {actors}")

    return diffs


def evaluate(status: int, body: object, intended: dict, name: str) -> tuple[int, str]:
    """Decide the verdict from an HTTP status and payload. Pure; no network.

    Split out from the request so the decision table is testable offline, which
    is the part that must never be wrong.
    """
    if status == 200:
        rulesets = body if isinstance(body, list) else [body]
        match = next(
            (r for r in rulesets if isinstance(r, dict) and r.get("name") == name), None
        )
        if match is None:
            found = [r.get("name") for r in rulesets if isinstance(r, dict)]
            return FAIL, (
                f"DRIFT: no ruleset named {name!r} on this repository. Found: {found or 'none'}. "
                "main is unprotected, or the ruleset was renamed."
            )
        diffs = compare(intended, match)
        if diffs:
            return FAIL, "DRIFT: live protection no longer matches the file:\n  - " + "\n  - ".join(
                diffs
            )
        return OK, f"Live ruleset {name!r} matches .github/rulesets/main.json."

    if status == 404:
        return FAIL, (
            "DRIFT: the rulesets endpoint returned 404. Either the repository has no "
            "rulesets, or this token cannot see them. main is not verifiably protected."
        )
    if status in (401, 403):
        return FAIL, (
            f"CANNOT VERIFY: HTTP {status}. The token cannot read repository rulesets. "
            "The Actions GITHUB_TOKEN has no administration scope and cannot be granted "
            "one via `permissions:`; set secrets.PROTECTION_READ_TOKEN to a PAT with "
            "repository administration:read. Not treating this as a pass."
        )
    return FAIL, f"CANNOT VERIFY: unexpected HTTP {status} from the rulesets endpoint."


def _fetch(repo: str, token: str) -> tuple[int, object]:
    req = urllib.request.Request(
        f"{_API}/repos/{repo}/rulesets?includes_parents=false",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "weebot-protection-drift",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return exc.code, {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", _DEFAULT_REPO))
    args = parser.parse_args(argv)

    try:
        intended = json.loads(_RULESET.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {_RULESET}: {exc}", file=sys.stderr)
        return FAIL

    print("=== branch protection drift ===")
    print(f"repository: {args.repo}")
    print(f"intended:   {_RULESET.relative_to(_ROOT)} (ruleset {intended.get('name')!r})")

    token = os.environ.get("PROTECTION_READ_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "CANNOT VERIFY: no token in PROTECTION_READ_TOKEN or GITHUB_TOKEN. "
            "Refusing to report success without reading the live configuration.",
            file=sys.stderr,
        )
        return FAIL

    try:
        status, body = _fetch(args.repo, token)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"CANNOT VERIFY: request to the rulesets endpoint failed: {exc}", file=sys.stderr)
        return FAIL

    code, message = evaluate(status, body, intended, intended.get("name", "main"))
    print(message, file=sys.stderr if code else sys.stdout)
    if code:
        print(
            "\nTo restore protection, apply the checked-in ruleset:\n"
            "  see .github/rulesets/README.md",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
