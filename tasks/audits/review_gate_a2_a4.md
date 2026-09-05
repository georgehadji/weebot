# Part A, phases A2 and A4 — protection as code, and the two histories

Execution record for A2 and A4 of
[`tasks/specs/review_gate_and_residual_work_plan.md`](../specs/review_gate_and_residual_work_plan.md).
A0 and A1 are recorded in PR #59; this covers what followed on the same branch.

**Baseline:** `f4de8ba` (A0–A1), itself on `3fd25df`. Working tree clean.

---

## The `[UNK]` the plan flagged, now measured

§2.3 named a precondition to verify before A-i: *"whether the repository is
public or private, and the account's plan."*

| Fact | Value | How |
|---|---|---|
| Visibility | **private** | `search_repositories` → `"private": true`, `"visibility": "private"` |
| Session token's repo permission | **admin: true** | same call, `"permissions"` |
| `main` protected | **no** | `list_branches` → `"protected": false` |
| Account plan | **`[UNK]`** | `get_me` returns no `plan` field; no tool exposes it |

So the authority exists — the token is an admin token — but **no tool in this
session can apply protection.** The GitHub MCP server has no
branch-protection or ruleset endpoint, and the session has no `gh` CLI and no
direct API access. `[VF]` by enumerating the available tool surface.

That splits A2 cleanly, and the split is worth stating plainly rather than
blurring: **the intended protection, and everything that verifies it, is
written and proven. The protection itself is not applied.** A2's exit criterion
is met for the "readable from the repo" half and not for the "live" half.

---

## A2 — what was built

| # | File | Role |
|---|---|---|
| 1 | `.github/rulesets/main.json` | The intended protection, in the exact shape the rulesets API accepts |
| 2 | `scripts/check_ruleset_consistency.py` | **Offline, blocking.** Ruleset ↔ workflow agreement |
| 3 | `scripts/check_branch_protection.py` | **Online, scheduled.** Live state vs the file |
| 4 | `.github/workflows/protection-drift.yml` | Runs #3 daily. Not a PR check |
| 5 | `tests/unit/test_ruleset_consistency.py` | 29 tests proving #2 and #3 |
| 6 | `.github/rulesets/README.md` | Runbook, and why there is no review requirement |

### The design decision that carries the most weight

The plan's §2.3 established that `required_approving_review_count: 1` is a
**deadlock** here, not a gate: GitHub forbids self-approval, and the agent
shares the owner's identity, so nobody could approve anything. The ruleset
therefore sets **0**, and the README says why in the first section rather than a
footnote. A future reader who "fixes" that 0 to a 1 locks the repository.

### Why the consistency check is the more valuable half

It needs no token, no permissions and no network, so it works today and blocks
on every PR. It exists because **GitHub validates required-check names against
nothing**, which makes two opposite failures completely silent:

- **Rename a job** → the ruleset requires a context nothing reports → every PR
  waits forever on `Expected — Waiting for status to be reported`, with no error
  anywhere explaining why. The usual fix is to delete the protection.
- **Add a job and forget to require it** → it goes red while the merge button
  stays green.

The invariant is two-way, and A1's naming convention is what makes it decidable:
**required contexts == job names that do not say "advisory"**.

`[VF] Proven on disk.` Renaming `Unit Tests` → `Unit tests` — one character —
produced both errors at once and exit 1; restoring gave exit 0.

### Why the drift job never exits 0 on an unreadable answer

`check_branch_protection.py` returns 0 in exactly one case: it read the live
ruleset and it matched. No token, 401, 403, 404, an unexpected status, a network
error and a malformed payload are all failures. **"I could not check" must never
read as "nothing is wrong"** — that is the C2 fail-open class the nine waves
were spent removing, and it would be self-defeating to reintroduce it in the
control that guards the controls.

`[VF] Proven by sabotage.` Changing the 403 branch from `FAIL` to `OK` — a
two-character edit — turned the suite red on both the 401 and 403 cases;
reverting restored 29/29.

### Why the drift job does not run on pull requests

Branch protection is a property of the repository, not of anyone's change. A
contributor cannot fix it and must not be blocked by it; a required check nobody
can satisfy trains people to route around CI, which is how gates get switched
off. It runs on `schedule`, `workflow_dispatch`, and pushes that touch its own
inputs.

**It is expected to be red until a human acts**, and that redness is the correct
report of the present state — `main` really is unprotected. The workflow header
says so, so nobody mistakes it for a broken job.

---

## A4 — `master` is not stale, and the plan was wrong about it

The plan called it *"a stale `master` branch … unreferenced by CI"* and offered
*delete or document*. Only the second clause survived contact with the data.

`[VF]` `git merge-base main master` **exits 1 with no output.** The two branches
share no common ancestor at all.

| | `main` | `master` |
|---|---|---|
| Commits | 120 | **490** |
| Root commits | four | one |
| Span | 2026-07-21 → 2026-09-05 | 2026-02-28 → 2026-07-21 |
| Release tags | none | **`v2.0.0`, `v2.1.0`** |

`master` holds **both** of the repository's release tags and five months of
history unreachable from `main`. It is referenced by no workflow and no Makefile
target, so it costs nothing to keep — that part of the plan's claim held.

**Verdict: document, do not delete.** Written up in
[`docs/BRANCHES.md`](../../docs/BRANCHES.md), including the tag-first procedure
should anyone decide otherwise later. `[INFERENCE]` The chronology — `main`'s
first commit five hours after `master`'s last, on the same day, with no
ancestry, plus three further parentless roots — reads as a restart with contents
carried across and history not. Stated as inference; nobody was asked.

---

## Corrections to A0–A1, made here

1. **`Security Scan (advisory)` "cannot fail" was imprecise.** Its scanners are
   `continue-on-error`, but its `Install dependencies` step is not, so the job
   *can* fail — on a package-index outage. The sharper statement, and the
   stronger reason to keep it out of the required set: **it blocks on
   infrastructure and passes on a CVE.** The A1 test already excluded that step
   from its can-fail model; the exclusion was undocumented and is now explained
   where it is made.
2. **The exit-code rule now scans every workflow**, not only
   `architecture.yml`. A new workflow file is exactly where `|| echo` would come
   back. `[VF]` Planting one in `protection-drift.yml` turned the test red,
   naming the file, job and step.

---

## Phase 6 — six-vector self-review

| Vector | Finding |
|---|---|
| **Boundary** | `[VF]` Empty required-check list, ruleset with no `required_status_checks` rule, and a workflow with zero jobs are all covered. A job with only setup steps is asserted non-failable. |
| **Invalid input** | `[VF]` `evaluate` is asserted against `"not json"`, `42`, `None`, `[None]` and `[{"unrelated": True}]` — none reaches a pass. Unreadable ruleset/workflow files exit 1. |
| **State** | `[VF]` Both scripts are pure reads. Neither mutates the repository, and the drift script cannot: it issues only a `GET`. |
| **Regression** | `[VF]` Full suite 3825 passed / 0 failed (3796 before). Four ratchets unchanged at 139 / 29 / 143 / 73. import-linter 7 kept / 0 broken. Architecture fitness 51 passed. |
| **Concurrency** | Not applicable — no shared state, no async, no I/O beyond one HTTPS GET. |
| **New defects** | `[HYP]` The consistency check governs `architecture.yml` only. A failable job added in a *different* workflow escapes the required-set rule. Deliberate — the drift job is itself such a job — but it is a real gap, recorded in the README rather than papered over. |

---

## Phase 8 — coverage & residual risk

### Not covered — stated plainly

- **The ruleset is not applied.** `main` is still `"protected": false`. Nothing
  here changes that, and no test in this change can prove protection works,
  because there is no protection to test. The README's three-step *prove it
  blocks* procedure — direct push rejected, failing check blocks merge, drift
  job green — **has not been executed**, and A2's exit criterion is only half
  met until it is.
- **The drift script's live path is unproven.** Its decision table is proven
  offline against fixtures; the actual HTTP call has never run. Its first real
  execution is the experiment.
- **`[UNK]` Whether this account's plan permits rulesets on a private
  repository.** Not determinable from any tool in this session. If the answer is
  no, A2 is a billing decision. The `POST` in the README will settle it.
- **`[UNK]` Whether the Actions `GITHUB_TOKEN` can read rulesets at all.**
  `administration` is not among the scopes grantable via the workflow
  `permissions:` key, so the expectation is 403 and a PAT requirement — but that
  is reasoning from the documented scope list, not from an observed response.
  The script handles both outcomes without passing on either.
- **A3 — the distinct agent identity — is untouched**, and it remains the only
  measure that actually stops an agent merging its own work. It needs a human to
  register a GitHub App or bot account.

### Residual risks

- **R-1 — a permanently red scheduled job becomes wallpaper.** Mitigated by
  keeping it off PR CI and stating the expected-red condition in the workflow
  header, but a job that stays red for weeks stops being read. If A2 is not
  going to be applied, this workflow should be removed rather than left rotting.
- **R-2 — `strict_required_status_checks_policy: true` serialises merges.**
  With ~15 open dependabot branches, each merge invalidates the rest and forces
  a re-run. Correct but slow; the answer at scale is a merge queue, not turning
  it off. Flagged in the README so the trade-off is visible before it bites.
- **R-3 — `bypass_actors: []` means no emergency lane.** A repository admin can
  still disable the ruleset outright, which the drift job then reports. That is
  the intended shape — bypass should be visible — but it does mean an urgent fix
  requires switching protection off and back on.
- **R-4 — the consistency check enforces a convention, not a truth.** It trusts
  the word "advisory" in a job name. Renaming a genuinely blocking job to
  include "advisory" would silently drop it from the required set. The A1
  honesty tests constrain the other direction (an unfailable job *must* say
  advisory); nothing stops a failable one from lying.

### Verdict

**PARTIAL.** The intended protection is now data in the repository, two
verifiers guard it from opposite sides, and both are proven — one by disk
perturbation, one by sabotage. The protection itself is not applied and cannot
be from this session. A4 is closed, with its premise corrected.
