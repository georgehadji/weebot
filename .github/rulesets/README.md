# Branch protection, as code

`main.json` is the protection `main` is meant to have. It is the exact request
body GitHub's rulesets API expects, so it can be applied verbatim and read back
for comparison.

Phase A2 of [`tasks/specs/review_gate_and_residual_work_plan.md`](../../tasks/specs/review_gate_and_residual_work_plan.md).

**Status: this file describes the intended state. It has not been applied.**
`main` is currently unprotected (`list_branches` → `"protected": false`).
Applying it requires an authenticated admin call, which the session that wrote
this file could not make — see [Applying it](#applying-it).

---

## Why there is no review requirement

This is the part that is easy to get wrong, and the reason the plan spends a
section on it.

The goal — *an agent should not be able to merge without human sign-off* —
**cannot be expressed with `required_approving_review_count: 1` on this
repository**, because:

1. GitHub forbids approving your own pull request.
2. The agent acts with the repository owner's identity, so the author and the
   only possible approver are the same principal.

Requiring one approval therefore does not create a gate. It creates a
**deadlock**: nobody can approve, including the owner working alone. So the
ruleset sets `required_approving_review_count: 0`, which still forces every
change through a pull request and still runs every required check, but does not
pretend to enforce review.

**Closing that half needs a distinct identity for the agent** — a GitHub App or
bot account — after which `1` works exactly as intended: the bot opens, the
human approves. That is phase A3, and it needs a human to register the App.
Until then this ruleset stops *broken* code landing, not *unreviewed* code, and
saying otherwise would be the same false-assurance problem the ruleset exists
to fix.

A workflow that fails unless a human applies a `reviewed` label was considered
and rejected: the agent holds the same token and could apply the label itself.

---

## What it enforces

| Rule | Effect |
|---|---|
| `deletion` | `main` cannot be deleted |
| `non_fast_forward` | `main` cannot be force-pushed — without this the required checks are trivially bypassable |
| `pull_request` | every change arrives via a PR; 0 approvals required (see above) |
| `required_status_checks` | the eight jobs below must pass, and the branch must be up to date first |

Required checks — every job in `architecture.yml` that can fail on its own
subject matter:

`Lint + Architecture` · `Unit Tests` · `Persistence Tests` ·
`CQRS Integration Tests` · `E2E / Performance / Chaos Tests` ·
`Frontend Quality Gates` · `Security Scan (blocking)` ·
`Docker Build Smoke Test`

**`Security Scan (advisory)` is deliberately excluded.** Its scanners are
`continue-on-error`, so its only blocking step is `pip install`. Requiring it
would block merges on a package-index outage while still never blocking on a
CVE — strictly worse than not requiring it.

`strict_required_status_checks_policy: true` means a branch must be up to date
with `main` before merging. The cost is a re-run when `main` moves; the benefit
is that two PRs which each pass against an older `main` cannot combine into a
broken one. With ~15 dependabot branches open that is a live risk, not a
hypothetical. If the re-run loop becomes painful, the answer is a merge queue,
not turning this off.

`bypass_actors` is empty: nobody bypasses. A repository admin can still disable
the ruleset outright in an emergency — which is what the drift job reports.

---

## Applying it

Requires **admin** on the repository. Either:

```bash
gh api --method POST /repos/georgehadji/weebot/rulesets \
  --input .github/rulesets/main.json
```

```bash
curl -X POST https://api.github.com/repos/georgehadji/weebot/rulesets \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -d @.github/rulesets/main.json
```

To update an existing ruleset, `PUT` to `/rulesets/{id}` instead; get the id
from `GET /repos/georgehadji/weebot/rulesets`.

**Unverified precondition.** `georgehadji/weebot` is a **private** repository.
Availability of rulesets and of classic branch protection on private
repositories depends on the account plan and has changed over time. This has
not been confirmed for this account. If the `POST` is rejected on plan grounds
then A2 is a billing decision rather than a configuration one — the command
above will say so, and that answer is worth having either way.

### Then prove it blocks

A gate assumed to work is not a gate. After applying:

1. `git push origin main` directly → must be **rejected**.
2. Open a PR with a deliberately failing check → merge must be **blocked**.
3. Run the drift job (Actions → Protection Drift → Run workflow) → must be
   **green**.

If step 3 is red while 1 and 2 pass, the token cannot read rulesets — see
below.

---

## Keeping it honest

Two checks guard this file, and they are separate because they fail differently.

**`scripts/check_ruleset_consistency.py`** — offline, blocking, runs in
`Lint + Architecture` on every PR. It needs no token and no permissions. GitHub
validates required-check names against nothing, so it catches the two silent
failures:

- A **renamed job** leaves this file requiring a context nothing reports, and
  every PR then waits on it forever with no error explaining why. The usual fix
  is to delete the protection.
- A **new job nobody requires** is red while the merge button stays green.

The rule it enforces is two-way: *the set of required contexts equals the set of
job names that do not say "advisory"*.

**`scripts/check_branch_protection.py`** — online, scheduled daily via
`.github/workflows/protection-drift.yml`. It reads the live ruleset back and
compares. **It exits 0 only when it has read the configuration and found it
matching**; no token, 403, 404, and network errors are all failures, because a
drift detector that passes when it cannot see is the fail-open control this
whole exercise removes.

It needs `secrets.PROTECTION_READ_TOKEN` — a PAT with repository
`administration: read`. The Actions `GITHUB_TOKEN` cannot be granted that scope
through the workflow `permissions:` key, so it will most likely 403, which the
script reports as `CANNOT VERIFY` and fails on.

**Known limitation:** the consistency check governs `architecture.yml` only. A
failable job added in a *different* workflow file will not be flagged as
un-required. That is deliberate — the drift workflow itself is such a job, and
repository-configuration checks must not block PRs — but it means a second CI
workflow would need this scope widened by hand.
